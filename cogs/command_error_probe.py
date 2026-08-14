"""Expose un diagnostic minimal des dernieres erreurs de commandes.

Les metriques V9 contiennent deja le nom de commande, son type, sa duree et le detail de
l'exception. Cette sonde ne publie jamais guild_id/user_id ni le message d'erreur complet :
elle conserve uniquement la classe d'exception afin de pouvoir retrouver le handler fautif.
"""
from __future__ import annotations

import asyncio
import re
import time

from discord.ext import commands


_ERROR_TYPE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]{0,119})\s*:")


def _state(bot: commands.Bot) -> dict:
    state = getattr(bot, "command_error_probe_state", None)
    if not isinstance(state, dict):
        state = {
            "installed": False,
            "updated_at": None,
            "latest_metric": None,
            "latest_error": None,
            "last_error": None,
        }
        bot.command_error_probe_state = state
    return state


def _error_type(detail: object) -> str | None:
    value = str(detail or "").strip()
    match = _ERROR_TYPE.match(value)
    if match:
        return match.group(1)[:120]
    return None


def _safe_row(row) -> dict | None:
    if not row:
        return None
    return {
        "command_name": str(row["command_name"] or "unknown")[:120],
        "command_kind": str(row["command_kind"] or "unknown")[:20],
        "duration_ms": max(0, int(row["duration_ms"] or 0)),
        "status": str(row["status"] or "unknown")[:30],
        "error_type": _error_type(row["detail"]),
        "created_at": int(row["created_at"] or 0),
    }


def _safe_health(bot: commands.Bot) -> dict:
    state = _state(bot)
    return {
        "installed": bool(state.get("installed")),
        "updated_at": state.get("updated_at"),
        "latest_metric": state.get("latest_metric"),
        "latest_error": state.get("latest_error"),
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
        latest = await bot.db.fetchone(
            "SELECT command_name,command_kind,duration_ms,status,detail,created_at "
            "FROM production_command_metrics ORDER BY id DESC LIMIT 1"
        )
        latest_error = await bot.db.fetchone(
            "SELECT command_name,command_kind,duration_ms,status,detail,created_at "
            "FROM production_command_metrics WHERE status='error' ORDER BY id DESC LIMIT 1"
        )
        state["latest_metric"] = _safe_row(latest)
        state["latest_error"] = _safe_row(latest_error)
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
