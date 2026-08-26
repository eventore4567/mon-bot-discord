"""V5.1 — garantit que les listeners de logs existent réellement en production.

Le setup historique de ``cogs.logs`` initialise le cache SQLite AVANT ``add_cog``. Une
DB verrouillée ou une migration de cache défaillante peut donc empêcher l'enregistrement
de tous les listeners Discord. Cette couche finale sépare les deux responsabilités : le
cache est best-effort, mais le Cog Logs est toujours enregistré.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from discord.ext import commands

logger = logging.getLogger("bot.log-listener-guarantee-v51")


def _state(bot: commands.Bot) -> dict[str, Any]:
    state = getattr(bot, "log_listener_guarantee_v51_state", None)
    if not isinstance(state, dict):
        state = {
            "installed": False,
            "cog_present": False,
            "listener_count": 0,
            "cache_ready": False,
            "direct_cog_recovery": False,
            "last_error": None,
            "checked_at": None,
        }
        bot.log_listener_guarantee_v51_state = state
    return state


async def _best_effort_cache(bot: commands.Bot) -> bool:
    try:
        from .logs import MESSAGE_CACHE_SCHEMA, MESSAGE_CACHE_RETENTION_SECONDS

        await bot.db.execute(MESSAGE_CACHE_SCHEMA)
        await bot.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_message_log_cache_stored_at "
            "ON message_log_cache(stored_at)"
        )
        await bot.db.execute(
            "DELETE FROM message_log_cache WHERE stored_at < ?",
            (int(time.time()) - MESSAGE_CACHE_RETENTION_SECONDS,),
        )
        return True
    except Exception:
        # Le cache améliore les raw-delete logs, mais ne doit JAMAIS couper tous les
        # listeners si la DB est momentanément verrouillée ou fraîchement recréée.
        logger.exception("V5.1 : cache message logs indisponible ; listeners conservés.")
        return False


def _listener_count(cog) -> int:
    if cog is None:
        return 0
    try:
        return len(cog.get_listeners())
    except Exception:
        return 0


async def ensure_logs_cog(bot: commands.Bot) -> tuple[bool, int]:
    state = _state(bot)
    state["checked_at"] = int(time.time())
    state["last_error"] = None

    cog = bot.get_cog("Logs")
    listeners = _listener_count(cog)
    if cog is not None and listeners > 0:
        state.update({"cog_present": True, "listener_count": listeners})
        return True, listeners

    try:
        from .logs import Logs

        # Si un objet incomplet existe, on le remplace proprement par l'autorité officielle.
        if cog is not None:
            await bot.remove_cog("Logs")
        await bot.add_cog(Logs(bot))
        cog = bot.get_cog("Logs")
        listeners = _listener_count(cog)
        state["direct_cog_recovery"] = True
        logger.warning(
            "V5.1 : Cog Logs enregistré directement après échec/absence du setup ; listeners=%s.",
            listeners,
        )
    except Exception as exc:
        state["last_error"] = type(exc).__name__
        logger.exception("V5.1 : impossible d'enregistrer directement le Cog Logs.")
        cog = bot.get_cog("Logs")
        listeners = _listener_count(cog)

    state.update({"cog_present": cog is not None, "listener_count": listeners})
    return cog is not None and listeners > 0, listeners


def _install_health(bot: commands.Bot) -> None:
    try:
        from web import production_health
    except Exception:
        return
    current = production_health._safe_slash_health
    if getattr(current, "_sentrix_log_listener_v51_health", False):
        return

    def health(runtime_bot: commands.Bot):
        payload = current(runtime_bot)
        if not isinstance(payload, dict):
            payload = {}
        payload["log_listener_guarantee_v51"] = dict(_state(runtime_bot))
        return payload

    health._sentrix_log_listener_v51_health = True
    health._sentrix_original = current
    production_health._safe_slash_health = health


async def install(bot: commands.Bot) -> None:
    state = _state(bot)
    state["installed"] = True
    # Le cache est tenté, mais son résultat n'empêche jamais le Cog d'être présent.
    state["cache_ready"] = await _best_effort_cache(bot)
    loaded, listeners = await ensure_logs_cog(bot)
    state.update({"cog_present": loaded, "listener_count": listeners})
    _install_health(bot)
    logger.info(
        "V5.1 listeners logs : cog=%s listeners=%s cache=%s direct_recovery=%s.",
        loaded,
        listeners,
        state.get("cache_ready"),
        state.get("direct_cog_recovery"),
    )


__all__ = ["install", "ensure_logs_cog"]
