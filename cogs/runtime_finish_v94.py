"""V94 — sauvegarde durable immédiate des réglages tickets.

Un déploiement Railway peut démarrer juste après une modification de panel. Les snapshots
PostgreSQL périodiques/graceful peuvent alors être trop anciens au moment où le nouveau
conteneur restaure sa SQLite. Cette garde marque les écritures de configuration ticket et
programme un snapshot durable très rapidement, sans bloquer l'interaction Discord.
"""
from __future__ import annotations

import asyncio
import logging

from discord.ext import commands

from . import runtime_finish_v93 as v93

logger = logging.getLogger("bot.runtime-finish-v94")

_TICKET_CONFIG_TABLES = (
    "ticket_panels_v2",
    "ticket_types",
    "ticket_form_questions",
    "ticket_button_settings",
)


def _is_ticket_config_write(query: object) -> bool:
    sql = " ".join(str(query or "").casefold().split())
    if not sql.startswith(("insert ", "update ", "delete ", "replace ")):
        return False
    return any(table in sql for table in _TICKET_CONFIG_TABLES)


def _schedule_ticket_snapshot(bot: commands.Bot) -> None:
    durable = getattr(bot, "sentrix_durable_store", None)
    if durable is None or not getattr(durable, "configured", False):
        return

    seq = int(getattr(bot, "_sentrix_ticket_snapshot_seq", 0)) + 1
    bot._sentrix_ticket_snapshot_seq = seq

    current_task = getattr(bot, "_sentrix_ticket_snapshot_task", None)
    if current_task is not None and not current_task.done():
        return

    async def runner() -> None:
        try:
            while True:
                seen = int(getattr(bot, "_sentrix_ticket_snapshot_seq", 0))
                # Court debounce : plusieurs champs enregistrés d'affilée produisent un seul
                # snapshot, tout en restant bien plus rapide qu'un redéploiement Railway.
                await asyncio.sleep(0.6)
                if seen != int(getattr(bot, "_sentrix_ticket_snapshot_seq", 0)):
                    continue
                try:
                    result = await durable.snapshot(reason="ticket_config_write", clean_shutdown=False)
                    if not result.get("stored"):
                        logger.warning("Snapshot ticket non stocké : %s", result)
                except Exception:
                    logger.exception("Snapshot durable des réglages tickets impossible.")
                # Si une nouvelle écriture est arrivée pendant le snapshot, refait un tour
                # afin que la dernière modification soit elle aussi durable.
                if seen == int(getattr(bot, "_sentrix_ticket_snapshot_seq", 0)):
                    break
        finally:
            bot._sentrix_ticket_snapshot_task = None

    bot._sentrix_ticket_snapshot_task = asyncio.create_task(
        runner(), name="sentrix-ticket-config-snapshot"
    )


def _patch_database_execute(bot: commands.Bot) -> bool:
    db = getattr(bot, "db", None)
    if db is None:
        return False
    current = getattr(db, "execute", None)
    if current is None or getattr(current, "_sentrix_v94_ticket_snapshot", False):
        return bool(current)

    async def execute_v94(query: str, params: tuple = ()):
        cursor = await current(query, params)
        if _is_ticket_config_write(query):
            _schedule_ticket_snapshot(bot)
        return cursor

    execute_v94._sentrix_v94_ticket_snapshot = True
    execute_v94._sentrix_previous = current
    db.execute = execute_v94
    return True


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_runtime_finish_v94", False):
        return
    await v93.install(bot)
    _patch_database_execute(bot)
    bot._sentrix_runtime_finish_v94 = True


__all__ = ["install"]
