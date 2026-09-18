"""Interrupteurs Économie / Niveaux : façade sur ``module_settings``.

Historique : ces deux interrupteurs vivaient dans une table ``system_features``
séparée (économie et niveaux « activés par défaut »), pendant que /setup et la matrice
d'accès lisaient ``module_settings``. Deux sources de vérité : le Dashboard pouvait dire
ON quand Discord disait OFF. Il n'y en a plus qu'une : ``module_settings`` via
``cogs.setup_v2_core`` (absence de ligne = non configuré = inactif). Cette façade garde
l'API historique (``get_system_features``/``set_system_feature``/``is_system_enabled``)
pour les appelants qui ne manipulent qu'un ``db``.

L'ancienne table n'est plus écrite ; ses valeurs explicites ont été reprises une fois
par ``setup_v2_core.migrate_module_defaults``.
"""
from __future__ import annotations

from types import SimpleNamespace

_FEATURE_MODULES = {
    "economy": "economy", "money": "economy", "argent": "economy", "economy_enabled": "economy",
    "levels": "levels", "level": "levels", "xp": "levels", "niveaux": "levels", "levels_enabled": "levels",
}
_COLUMN_FOR_MODULE = {"economy": "economy_enabled", "levels": "levels_enabled"}


def _module_for(feature: str) -> str:
    module = _FEATURE_MODULES.get(str(feature).strip().lower())
    if module is None:
        raise ValueError(f"Système inconnu : {feature}")
    return module


def _bot_like(db):
    # setup_v2_core n'utilise que ``bot.db`` et des attributs de verrou posés sur l'objet.
    holder = getattr(db, "_sentrix_module_holder", None)
    if holder is None:
        holder = SimpleNamespace(db=db)
        try:
            db._sentrix_module_holder = holder
        except Exception:
            pass
    return holder


async def ensure_feature_table(db) -> None:
    """Conservé pour compatibilité : le schéma des modules est géré par setup_v2_core."""
    from cogs import setup_v2_core

    await setup_v2_core.ensure_schema(_bot_like(db))


async def get_system_features(db, guild_id: int, *, fresh: bool = False) -> dict[str, bool]:
    """``{"economy_enabled": bool, "levels_enabled": bool}`` depuis module_settings."""
    from cogs import setup_v2_core

    holder = _bot_like(db)
    if fresh:
        setup_v2_core.invalidate_module_cache(int(guild_id))
    return {
        column: await setup_v2_core.module_enabled(holder, int(guild_id), module)
        for module, column in _COLUMN_FOR_MODULE.items()
    }


async def is_system_enabled(db, guild_id: int, feature: str) -> bool:
    """feature accepte ``economy``/``economy_enabled`` ou ``levels``/``levels_enabled``."""
    from cogs import setup_v2_core

    return await setup_v2_core.module_enabled(_bot_like(db), int(guild_id), _module_for(feature))


async def set_system_feature(db, guild_id: int, feature: str, enabled: bool) -> dict[str, bool]:
    from cogs import setup_v2_core

    await setup_v2_core.set_module_enabled(_bot_like(db), int(guild_id), _module_for(feature), bool(enabled))
    return await get_system_features(db, guild_id, fresh=True)


def invalidate_system_feature_cache(db, guild_id: int | None = None) -> None:
    from cogs import setup_v2_core

    setup_v2_core.invalidate_module_cache(None if guild_id is None else int(guild_id))
