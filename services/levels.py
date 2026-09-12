"""LevelsService — Core V2, Phase 4 (docs/core-v2-plan.md).

cogs/levels.py::Levels._apply_xp_delta() est le point d'entrée UNIQUE partagé
par le gain d'XP passif (chaque message), +add-xp et +set-xp (voir
tests/test_setxp_level_recalc.py : +set-xp écrivait autrefois `xp` sans
recalculer `level`, corrigé en passant par cette même méthode). C'est déjà
une fonction "service-shaped" — aucun type discord.py au-delà de guild_id/
user_id, un verrou par membre pour rendre lecture-calcul-écriture atomique —
mais elle vivait dans le cog, jamais testée directement.

Cette extraction ne change AUCUN comportement : apply_xp_delta() reçoit le
même dict de verrous que celui du cog (`Levels._xp_locks`, créé au demande,
jamais purgé) au lieu de le porter lui-même, pour que le grain de verrouillage
reste identique à l'original. L'invalidation du cache de rang
(stats_service.invalidate_rank_cache(bot, ...)) reste dans le cog : elle a
besoin de `bot`, un type que les fonctions de service n'exposent jamais dans
leur signature (docs/core-v2-plan.md, section D)."""
from __future__ import annotations

import asyncio

from database.db import now
from utils import stats_service


def _get_lock(locks: dict[tuple[int, int], asyncio.Lock], guild_id: int, user_id: int) -> asyncio.Lock:
    key = (guild_id, user_id)
    lock = locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        locks[key] = lock
    return lock


async def apply_xp_delta(
    db, locks: dict[tuple[int, int], asyncio.Lock], guild_id: int, user_id: int, delta: int,
) -> tuple[int, int, bool]:
    """Ajoute (ou retire) `delta` XP à un membre, sous verrou, en recalculant TOUJOURS
    le niveau correctement (jamais de xp qui dépasse le seuil du niveau courant sans
    faire monter le niveau). Retourne (nouveau_xp, nouveau_niveau, a_gagné_un_niveau)."""
    await db.ensure_level(guild_id, user_id)
    lock = _get_lock(locks, guild_id, user_id)
    async with lock:
        row = await db.get_level(guild_id, user_id)
        new_xp = max(0, row["xp"] + delta)
        level = row["level"]
        needed = stats_service.xp_required_for_level(level)
        leveled_up = False
        while new_xp >= needed:
            new_xp -= needed
            level += 1
            needed = stats_service.xp_required_for_level(level)
            leveled_up = True
        # En cas de retrait d'XP (delta négatif), on ne fait jamais descendre le
        # niveau automatiquement — un admin qui veut baisser un niveau doit utiliser
        # +set-xp explicitement avec la valeur souhaitée, jamais un effet de bord.
        await db.execute(
            "UPDATE levels SET xp = ?, level = ?, updated_at = ? WHERE guild_id = ? AND user_id = ?",
            (new_xp, level, now(), guild_id, user_id),
        )
    return new_xp, level, leveled_up
