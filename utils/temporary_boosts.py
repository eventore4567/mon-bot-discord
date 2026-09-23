"""Boosts temporaires gagnés via les quêtes SentriX.

Le boost est volontairement simple et persistant :
- une seule ligne active par membre et serveur ;
- argent et XP partagent la même durée ;
- les boosts ne se multiplient jamais entre eux ;
- refaire une quête de même niveau pendant un boost actif ne rallonge pas sa durée ;
- un boost plus fort remplace le précédent, avec une durée bornée.

La table est créée paresseusement pour ne pas dépendre d'une migration Railway séparée.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

BOOST_SCHEMA = """
CREATE TABLE IF NOT EXISTS temporary_boosts (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    money_multiplier REAL NOT NULL DEFAULT 1.0,
    xp_multiplier REAL NOT NULL DEFAULT 1.0,
    expires_at INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'quest',
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
)
"""

MAX_DURATION_SECONDS = 30 * 60


@dataclass(frozen=True)
class TemporaryBoost:
    guild_id: int
    user_id: int
    money_multiplier: float
    xp_multiplier: float
    expires_at: int
    source: str = "quest"

    def remaining(self, now_ts: int | None = None) -> int:
        now_ts = int(time.time()) if now_ts is None else int(now_ts)
        return max(0, int(self.expires_at) - now_ts)

    @property
    def active(self) -> bool:
        return self.remaining() > 0


async def ensure_schema(db) -> None:
    if getattr(db, "_sentrix_temporary_boosts_schema", False):
        return
    await db.execute(BOOST_SCHEMA)
    db._sentrix_temporary_boosts_schema = True


def _row_value(row, key, default):
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        value = default
    return default if value is None else value


async def get_active_boost(db, guild_id: int, user_id: int, *, now_ts: int | None = None) -> TemporaryBoost | None:
    await ensure_schema(db)
    now_ts = int(time.time()) if now_ts is None else int(now_ts)
    row = await db.fetchone(
        "SELECT guild_id,user_id,money_multiplier,xp_multiplier,expires_at,source "
        "FROM temporary_boosts WHERE guild_id=? AND user_id=?",
        (int(guild_id), int(user_id)),
    )
    if row is None:
        return None

    expires_at = int(_row_value(row, "expires_at", 0))
    if expires_at <= now_ts:
        await db.execute(
            "DELETE FROM temporary_boosts WHERE guild_id=? AND user_id=?",
            (int(guild_id), int(user_id)),
        )
        return None

    return TemporaryBoost(
        guild_id=int(guild_id),
        user_id=int(user_id),
        money_multiplier=max(1.0, float(_row_value(row, "money_multiplier", 1.0))),
        xp_multiplier=max(1.0, float(_row_value(row, "xp_multiplier", 1.0))),
        expires_at=expires_at,
        source=str(_row_value(row, "source", "quest")),
    )


async def grant_quest_boost(
    db,
    guild_id: int,
    user_id: int,
    *,
    money_multiplier: float,
    xp_multiplier: float,
    duration_seconds: int,
    source: str = "quest",
    now_ts: int | None = None,
) -> tuple[TemporaryBoost, bool]:
    """Active un boost sans cumul abusif.

    Retourne (boost_actif, nouveau_boost_applique). Si un boost de force égale ou
    supérieure est déjà actif, il est conservé tel quel et sa durée n'est pas rallongée.
    """
    await ensure_schema(db)
    now_ts = int(time.time()) if now_ts is None else int(now_ts)
    duration = max(60, min(int(duration_seconds), MAX_DURATION_SECONDS))
    money = max(1.0, min(float(money_multiplier), 2.0))
    xp = max(1.0, min(float(xp_multiplier), 2.0))

    current = await get_active_boost(db, guild_id, user_id, now_ts=now_ts)
    if (
        current is not None
        and current.money_multiplier >= money
        and current.xp_multiplier >= xp
    ):
        return current, False

    expires_at = now_ts + duration
    await db.execute(
        """
        INSERT INTO temporary_boosts
          (guild_id,user_id,money_multiplier,xp_multiplier,expires_at,source,updated_at)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(guild_id,user_id) DO UPDATE SET
          money_multiplier=excluded.money_multiplier,
          xp_multiplier=excluded.xp_multiplier,
          expires_at=excluded.expires_at,
          source=excluded.source,
          updated_at=excluded.updated_at
        """,
        (
            int(guild_id),
            int(user_id),
            money,
            xp,
            expires_at,
            str(source or "quest")[:80],
            now_ts,
        ),
    )
    return TemporaryBoost(
        guild_id=int(guild_id),
        user_id=int(user_id),
        money_multiplier=money,
        xp_multiplier=xp,
        expires_at=expires_at,
        source=str(source or "quest")[:80],
    ), True


async def apply_money_boost(db, guild_id: int, user_id: int, amount: int) -> tuple[int, TemporaryBoost | None]:
    amount = max(0, int(amount))
    boost = await get_active_boost(db, guild_id, user_id)
    if boost is None or amount <= 0:
        return amount, boost
    return max(0, round(amount * boost.money_multiplier)), boost


async def apply_xp_boost(db, guild_id: int, user_id: int, amount: int) -> tuple[int, TemporaryBoost | None]:
    amount = int(amount)
    if amount <= 0:
        return amount, None
    boost = await get_active_boost(db, guild_id, user_id)
    if boost is None:
        return amount, None
    return max(1, round(amount * boost.xp_multiplier)), boost


def describe(boost: TemporaryBoost, *, now_ts: int | None = None) -> str:
    remaining = boost.remaining(now_ts)
    minutes = max(1, (remaining + 59) // 60)
    return (
        f"🚀 **Boost actif** · 🪙 Argent x{boost.money_multiplier:g} · "
        f"⭐ XP x{boost.xp_multiplier:g} · ⏱️ {minutes} min"
    )


def quest_boost_for_risk(risk_multiplier: float) -> tuple[float, float, int, str]:
    """Palier de boost selon le choix de quête : sûr, normal ou légendaire."""
    risk = float(risk_multiplier)
    if risk >= 1.5:
        return 1.30, 1.30, 20 * 60, "légendaire"
    if risk >= 1.0:
        return 1.20, 1.20, 15 * 60, "rare"
    return 1.10, 1.10, 10 * 60, "commun"
