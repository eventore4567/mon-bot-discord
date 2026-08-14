"""Expose un diagnostic minimal des erreurs agregees de commandes.

ProductionPhase utilise ``production_command_metrics`` comme table horaire avec une ligne
par nom de commande. Cette sonde lit ce schema reel et n'expose que nom, nombre d'appels,
erreurs et latence agregee. Aucun guild_id/user_id ni texte de message n'est present dans
ce schema.
"""
from __future__ import annotations

import asyncio
import time

from discord.ext import commands


def _state(bot: commands.Bot) -> dict:
    state = getattr(bot, "command_error_probe_state", None)
    if not isinstance(state, dict):
        state = {
            "installed": False,
            "updated_at": None,
            "latest_hour": None,
            "error_commands": [],
            "last_error": None,
        }
        bot.command_error_probe_state = state
    return state


def _safe_row(row) -> dict | None:
    if not row:
        return None
    calls = max(0, int(row["calls"] or 0))
    errors = max(0, int(row["errors"] or 0))
    total_ms = max(0.0, float(row["total_ms"] or 0.0))
    return {
        "hour_bucket": int(row["hour_bucket"] or 0),
        "command_name": str(row["command_name"] or "unknown")[:120],
        "calls": calls,
        "errors": errors,
        "error_rate_pct": round(errors * 100.0 / calls, 2) if calls else 0.0,
        "avg_ms": round(total_ms / calls, 1) if calls else 0.0,
        "max_ms": round(max(0.0, float(row["max_ms"] or 0.0)), 1),
    }


def _safe_health(bot: commands.Bot) -> dict:
    state = _state(bot)
    return {
        "installed": bool(state.get("installed")),
        "updated_at": state.get("updated_at"),
        "latest_hour": state.get("latest_hour"),
        "error_commands": list(state.get("error_commands") or [])[:12],
        "last_error": state.get("last_error"),
    }


def _install_health_patch() -> None:
    try:
        from web import production_health
    except Exception:
        return

    current = production_health._safe_slash_health
    if getattr(current, "_sentrix_command_error_probe", False):
        return

    def safe_slash_health_with_command_errors(bot):
        payload = current(bot)
        if not isinstance(payload, dict):
            payload = {}
        payload["command_error_probe"] = _safe_health(bot)
        return payload

    safe_slash_health_with_command_errors._sentrix_command_error_probe = True
    safe_slash_health_with_command_errors._sentrix_original = current
    production_health._safe_slash_health = safe_slash_health_with_command_errors


async def _refresh(bot: commands.Bot) -> None:
    state = _state(bot)
    try:
        latest_hour_row = await bot.db.fetchone(
            "SELECT MAX(hour_bucket) AS hour_bucket FROM production_command_metrics"
        )
        latest_hour = int(latest_hour_row["hour_bucket"] or 0) if latest_hour_row else 0
        rows = []
        if latest_hour:
            rows = await bot.db.fetchall(
                "SELECT hour_bucket,command_name,calls,errors,total_ms,max_ms "
                "FROM production_command_metrics "
                "WHERE hour_bucket=? AND errors>0 "
                "ORDER BY errors DESC,max_ms DESC,command_name ASC LIMIT 12",
                (latest_hour,),
            )
        state["latest_hour"] = latest_hour or None
        state["error_commands"] = [item for row in rows if (item := _safe_row(row)) is not None]
        state["updated_at"] = int(time.time())
        state["last_error"] = None
    except Exception as exc:
        state["last_error"] = type(exc).__name__
        state["updated_at"] = int(time.time())


async def _loop(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    while not bot.is_closed():
        await _refresh(bot)
        await asyncio.sleep(5)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_command_error_probe_installed", False):
        return
    bot._sentrix_command_error_probe_installed = True
    state = _state(bot)
    state["installed"] = True
    _install_health_patch()
    bot._sentrix_command_error_probe_task = asyncio.create_task(_loop(bot))


async def setup(bot: commands.Bot) -> None:
    install(bot)
