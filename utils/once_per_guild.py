"""Travaux ponctuels par serveur : faits une fois, plus jamais refaits au démarrage.

Plusieurs migrations (retrait des anciennes règles AutoMod natives de SentriX,
purge des commandes « / » locales…) tournaient à CHAQUE on_ready, sur CHAQUE
serveur — un appel Discord par serveur, à chaque redémarrage et reconnexion.
Mesuré (tools/scale_ready_probe.py) : 3 appels Discord par serveur au démarrage,
soit ~300 000 à 100 000 serveurs, contre la limite globale de ≈ 50 requêtes/s.

Ici, une ligne par (travail, serveur) terminé ; la liste de ce qui reste se lit
en UNE requête.
"""
from __future__ import annotations

import time
from typing import Iterable

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS sentrix_guild_tasks_done ("
    "task TEXT NOT NULL, guild_id INTEGER NOT NULL, done_at INTEGER NOT NULL, "
    "PRIMARY KEY (task, guild_id))"
)


async def _ensure(db) -> None:
    if getattr(db, "_sentrix_guild_tasks_ready", False):
        return
    await db.execute(SCHEMA)
    try:
        db._sentrix_guild_tasks_ready = True
    except AttributeError:
        pass


async def restants(bot, task: str, guild_ids: Iterable[int]) -> list[int]:
    """Les serveurs pour lesquels ``task`` n'a pas encore été fait (ordre conservé)."""
    ids = [int(g) for g in guild_ids]
    await _ensure(bot.db)
    rows = await bot.db.fetchall("SELECT guild_id FROM sentrix_guild_tasks_done WHERE task = ?", (task,))
    faits = {int(r["guild_id"]) for r in rows}
    return [g for g in ids if g not in faits]


async def marquer(bot, task: str, guild_id: int) -> None:
    await _ensure(bot.db)
    await bot.db.execute(
        "INSERT OR REPLACE INTO sentrix_guild_tasks_done (task, guild_id, done_at) VALUES (?, ?, ?)",
        (task, int(guild_id), int(time.time())),
    )


async def oublier(bot, task: str, guild_id: int) -> None:
    """À refaire pour ce serveur (il revient, par exemple)."""
    await _ensure(bot.db)
    await bot.db.execute(
        "DELETE FROM sentrix_guild_tasks_done WHERE task = ? AND guild_id = ?", (task, int(guild_id))
    )


__all__ = ["restants", "marquer", "oublier"]
