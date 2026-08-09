"""Interrupteurs persistants des grands systèmes SentriX.

Deux fonctions peuvent être coupées séparément par serveur :
- économie : monnaie + boutiques + récompenses monétaires ;
- niveaux : gains d'XP + commandes/paliers de niveau.

Les données existantes ne sont jamais supprimées quand un système est désactivé. Un serveur
peut donc le réactiver plus tard et reprendre exactement avec ses anciens soldes/niveaux.
"""
from __future__ import annotations

import time

FEATURE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS system_features (
    guild_id INTEGER PRIMARY KEY,
    economy_enabled INTEGER NOT NULL DEFAULT 1,
    levels_enabled INTEGER NOT NULL DEFAULT 1,
    updated_at INTEGER NOT NULL DEFAULT 0
)
"""

_DEFAULTS = {
    "economy_enabled": True,
    "levels_enabled": True,
}
_CACHE_TTL = 4.0
_READY_DB_IDS: set[int] = set()
_CACHE: dict[tuple[int, int], tuple[float, dict[str, bool]]] = {}


async def ensure_feature_table(db) -> None:
    db_id = id(db)
    if db_id in _READY_DB_IDS:
        return
    await db.execute(FEATURE_TABLE_SQL)
    _READY_DB_IDS.add(db_id)


async def get_system_features(db, guild_id: int, *, fresh: bool = False) -> dict[str, bool]:
    """Retourne les deux interrupteurs d'un serveur, activés par défaut."""
    await ensure_feature_table(db)
    key = (id(db), int(guild_id))
    now_mono = time.monotonic()
    cached = _CACHE.get(key)
    if not fresh and cached and now_mono - cached[0] <= _CACHE_TTL:
        return dict(cached[1])

    await db.execute(
        "INSERT OR IGNORE INTO system_features (guild_id, economy_enabled, levels_enabled, updated_at) "
        "VALUES (?, 1, 1, 0)",
        (int(guild_id),),
    )
    row = await db.fetchone(
        "SELECT economy_enabled, levels_enabled FROM system_features WHERE guild_id = ?",
        (int(guild_id),),
    )
    values = dict(_DEFAULTS)
    if row is not None:
        values["economy_enabled"] = bool(row["economy_enabled"])
        values["levels_enabled"] = bool(row["levels_enabled"])
    _CACHE[key] = (now_mono, values)
    return dict(values)


async def is_system_enabled(db, guild_id: int, feature: str) -> bool:
    """feature accepte ``economy``/``economy_enabled`` ou ``levels``/``levels_enabled``."""
    normalized = str(feature).strip().lower()
    if normalized in {"economy", "money", "argent", "economy_enabled"}:
        key = "economy_enabled"
    elif normalized in {"levels", "level", "xp", "niveaux", "levels_enabled"}:
        key = "levels_enabled"
    else:
        raise ValueError(f"Système inconnu : {feature}")
    return (await get_system_features(db, guild_id)).get(key, True)


async def set_system_feature(db, guild_id: int, feature: str, enabled: bool) -> dict[str, bool]:
    normalized = str(feature).strip().lower()
    if normalized in {"economy", "money", "argent", "economy_enabled"}:
        column = "economy_enabled"
    elif normalized in {"levels", "level", "xp", "niveaux", "levels_enabled"}:
        column = "levels_enabled"
    else:
        raise ValueError(f"Système inconnu : {feature}")

    await ensure_feature_table(db)
    guild_id = int(guild_id)
    await db.execute(
        "INSERT OR IGNORE INTO system_features (guild_id, economy_enabled, levels_enabled, updated_at) "
        "VALUES (?, 1, 1, ?)",
        (guild_id, int(time.time())),
    )
    await db.execute(
        f"UPDATE system_features SET {column} = ?, updated_at = ? WHERE guild_id = ?",
        (1 if enabled else 0, int(time.time()), guild_id),
    )
    _CACHE.pop((id(db), guild_id), None)
    return await get_system_features(db, guild_id, fresh=True)


def invalidate_system_feature_cache(db, guild_id: int | None = None) -> None:
    db_id = id(db)
    if guild_id is not None:
        _CACHE.pop((db_id, int(guild_id)), None)
        return
    for key in [key for key in _CACHE if key[0] == db_id]:
        _CACHE.pop(key, None)
