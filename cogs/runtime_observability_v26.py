"""Observabilité runtime SentriX — sans nouvelle commande.

Cette couche mesure uniquement des métadonnées techniques : durées de commandes,
latence des appels DB, nombre d'erreurs et commit déployé. Les paramètres SQL, contenus
de messages et réponses IA ne sont jamais stockés dans l'état d'observabilité.
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections import Counter, deque
from typing import Any

import discord
from discord.ext import commands

logger = logging.getLogger("bot.runtime-observability")

_SLOW_COMMAND_SECONDS = 2.0
_SLOW_DB_SECONDS = 0.250
_MAX_ERRORS = 80
_MAX_SLOW_COMMANDS = 80
_MAX_SLOW_DB = 80
_SQL_SPACE_RE = re.compile(r"\s+")


def _release_id() -> str:
    for key in (
        "RAILWAY_GIT_COMMIT_SHA",
        "GIT_COMMIT_SHA",
        "SOURCE_VERSION",
        "COMMIT_SHA",
    ):
        value = os.getenv(key, "").strip()
        if value:
            return value[:12]
    return "inconnu"


def _query_fingerprint(query: Any) -> str:
    """Garde la forme SQL, jamais les paramètres utilisateur."""
    text = _SQL_SPACE_RE.sub(" ", str(query or "")).strip()
    if not text:
        return "requête inconnue"
    return text[:140]


def _state(bot: commands.Bot) -> dict[str, Any]:
    state = getattr(bot, "_sentrix_observability_v26", None)
    if isinstance(state, dict):
        return state
    state = {
        "release": _release_id(),
        "started_at": int(time.time()),
        "db_calls": 0,
        "db_total_seconds": 0.0,
        "db_by_method": Counter(),
        "slow_db": deque(maxlen=_MAX_SLOW_DB),
        "command_count": 0,
        "command_total_seconds": 0.0,
        "slow_commands": deque(maxlen=_MAX_SLOW_COMMANDS),
        "errors": deque(maxlen=_MAX_ERRORS),
        "prefix_starts": {},
        "slash_starts": {},
    }
    bot._sentrix_observability_v26 = state
    return state


def _trim_start_maps(state: dict[str, Any]) -> None:
    now_value = time.monotonic()
    for key in ("prefix_starts", "slash_starts"):
        mapping = state[key]
        if len(mapping) <= 5000:
            continue
        stale = [item for item, started in mapping.items() if now_value - started > 300.0]
        for item in stale:
            mapping.pop(item, None)


def _record_db(bot: commands.Bot, method: str, query: Any, elapsed: float) -> None:
    state = _state(bot)
    state["db_calls"] += 1
    state["db_total_seconds"] += float(elapsed)
    state["db_by_method"][str(method)] += 1
    if elapsed >= _SLOW_DB_SECONDS:
        state["slow_db"].append(
            {
                "method": str(method),
                "ms": round(elapsed * 1000, 1),
                "query": _query_fingerprint(query),
                "at": int(time.time()),
            }
        )
        logger.warning("Requête DB lente : %s %.1fms — %s", method, elapsed * 1000, _query_fingerprint(query))


def _wrap_db_method(bot: commands.Bot, method_name: str) -> None:
    db = getattr(bot, "db", None)
    if db is None:
        return
    current = getattr(db, method_name, None)
    if current is None or getattr(current, "_sentrix_observability_v26", False):
        return

    async def measured(*args, **kwargs):
        query = args[0] if args else kwargs.get("query")
        started = time.perf_counter()
        try:
            return await current(*args, **kwargs)
        finally:
            _record_db(bot, method_name, query, time.perf_counter() - started)

    measured._sentrix_observability_v26 = True
    measured._sentrix_original = current
    setattr(db, method_name, measured)


def _command_key(ctx: commands.Context) -> int | None:
    message = getattr(ctx, "message", None)
    message_id = getattr(message, "id", None)
    return int(message_id) if message_id is not None else None


def _record_command_duration(bot: commands.Bot, name: str, elapsed: float, *, failed: bool) -> None:
    state = _state(bot)
    state["command_count"] += 1
    state["command_total_seconds"] += float(elapsed)
    if elapsed >= _SLOW_COMMAND_SECONDS:
        state["slow_commands"].append(
            {
                "command": str(name or "inconnue")[:100],
                "ms": round(elapsed * 1000, 1),
                "failed": bool(failed),
                "at": int(time.time()),
            }
        )


def record_error(
    bot: commands.Bot,
    *,
    command: str,
    error: BaseException,
    guild_id: int | None = None,
    user_id: int | None = None,
    reference: int | str | None = None,
    source: str = "prefix",
) -> None:
    """Enregistre seulement le type d'erreur et des identifiants techniques."""
    state = _state(bot)
    state["errors"].append(
        {
            "command": str(command or "inconnue")[:100],
            "type": type(error).__name__,
            "guild_id": int(guild_id) if guild_id is not None else None,
            "user_id": int(user_id) if user_id is not None else None,
            "reference": str(reference or "")[:40],
            "source": str(source)[:20],
            "at": int(time.time()),
            "release": state["release"],
        }
    )


def snapshot(bot: commands.Bot) -> dict[str, Any]:
    state = _state(bot)
    db_calls = int(state["db_calls"])
    command_count = int(state["command_count"])
    return {
        "release": state["release"],
        "db_calls": db_calls,
        "db_avg_ms": round((state["db_total_seconds"] / db_calls) * 1000, 2) if db_calls else 0.0,
        "slow_db_count": len(state["slow_db"]),
        "last_slow_db": dict(state["slow_db"][-1]) if state["slow_db"] else None,
        "command_count": command_count,
        "command_avg_ms": round((state["command_total_seconds"] / command_count) * 1000, 2) if command_count else 0.0,
        "slow_command_count": len(state["slow_commands"]),
        "last_slow_command": dict(state["slow_commands"][-1]) if state["slow_commands"] else None,
        "error_count": len(state["errors"]),
        "last_error": dict(state["errors"][-1]) if state["errors"] else None,
    }


def install(bot: commands.Bot) -> None:
    """Installation idempotente ; aucune commande et aucune modification métier."""
    _state(bot)
    for method_name in ("execute", "fetchone", "fetchall"):
        _wrap_db_method(bot, method_name)

    if getattr(bot, "_sentrix_observability_v26_installed", False):
        return

    async def prefix_start(ctx: commands.Context):
        key = _command_key(ctx)
        if key is None:
            return
        state = _state(bot)
        state["prefix_starts"][key] = time.perf_counter()
        _trim_start_maps(state)

    async def prefix_complete(ctx: commands.Context):
        key = _command_key(ctx)
        if key is None:
            return
        state = _state(bot)
        started = state["prefix_starts"].pop(key, None)
        if started is None:
            return
        name = getattr(getattr(ctx, "command", None), "qualified_name", "inconnue")
        _record_command_duration(bot, str(name), time.perf_counter() - started, failed=False)

    async def prefix_error(ctx: commands.Context, error: commands.CommandError):
        key = _command_key(ctx)
        state = _state(bot)
        started = state["prefix_starts"].pop(key, None) if key is not None else None
        name = getattr(getattr(ctx, "command", None), "qualified_name", "inconnue")
        original = getattr(error, "original", error)
        if started is not None:
            _record_command_duration(bot, str(name), time.perf_counter() - started, failed=True)
        record_error(
            bot,
            command=str(name),
            error=original,
            guild_id=getattr(getattr(ctx, "guild", None), "id", None),
            user_id=getattr(getattr(ctx, "author", None), "id", None),
            reference=getattr(getattr(ctx, "message", None), "id", None),
            source="prefix",
        )

    async def interaction_start(interaction: discord.Interaction):
        if interaction.type is not discord.InteractionType.application_command:
            return
        state = _state(bot)
        state["slash_starts"][int(interaction.id)] = time.perf_counter()
        _trim_start_maps(state)

    async def slash_complete(interaction: discord.Interaction, command):
        state = _state(bot)
        started = state["slash_starts"].pop(int(interaction.id), None)
        if started is None:
            return
        name = getattr(command, "qualified_name", getattr(command, "name", "inconnue"))
        _record_command_duration(bot, str(name), time.perf_counter() - started, failed=False)

    bot.add_listener(prefix_start, "on_command")
    bot.add_listener(prefix_complete, "on_command_completion")
    bot.add_listener(prefix_error, "on_command_error")
    bot.add_listener(interaction_start, "on_interaction")
    bot.add_listener(slash_complete, "on_app_command_completion")
    bot._sentrix_observability_v26_installed = True
    logger.info("Observabilité SentriX active : DB, commandes, erreurs et release; 0 nouvelle commande.")
