"""Compatibilité V5.3 — aucun transport legacy n'est encore autorisé.

Ce module reste importable parce que quelques outils historiques le référencent encore.
Il ne monkey-patch plus ``log_service.send_log`` ni ``Logs._send`` et n'envoie plus
``embed=...`` pour les journaux. Toute émission passe par ``utils.wide_logs``.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import discord
from discord.ext import commands

from utils import embeds, log_service
from utils.wide_logs import send_wide_log
from . import live_log_delivery_v5

logger = logging.getLogger("bot.log-transport-v53-compat")
_MARKER = "_sentrix_log_transport_v53"
_BOT: commands.Bot | None = None


def _state(bot: commands.Bot) -> dict[str, Any]:
    state = getattr(bot, "log_transport_v52_state", None)
    if not isinstance(state, dict):
        state = {
            "installed": False,
            "logs_send_patched": False,
            "attempts": 0,
            "sent": 0,
            "recovered": 0,
            "last_guild_id": None,
            "last_log_type": None,
            "last_channel_id": None,
            "last_result": None,
            "last_error": None,
            "last_error_message": None,
            "last_at": None,
        }
        bot.log_transport_v52_state = state
    state["logs_send_patched"] = False
    return state


def _unwrap_messageable_send():
    current = discord.abc.Messageable.send
    seen: set[int] = set()
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        original = (
            getattr(current, "_sentrix_original_send", None)
            or getattr(current, "_sentrix_original", None)
        )
        if not callable(original):
            break
        current = original
    return current


def _force_sentrix_log_icon(embed: discord.Embed) -> discord.Embed:
    return embed


def _force_command_divider(embed: discord.Embed) -> discord.Embed:
    return embed


def _render(embed: discord.Embed) -> discord.Embed:
    if not isinstance(embed, discord.Embed):
        return embed
    try:
        return embeds.normalize_log(embed)
    except Exception:
        logger.exception("V5.3 compat : normalisation impossible ; embed original conservé.")
        return embed


async def _resolve_setting(bot, guild: discord.Guild, log_type: str, *, needs_file: bool):
    setting = await log_service.get_log_setting(bot, guild.id, log_type)
    if setting and bool(setting.get("enabled")):
        valid, _reason = log_service.validate_channel(
            guild,
            setting.get("channel_id"),
            needs_file=needs_file,
        )
        if valid:
            return setting, False

    if setting and not bool(setting.get("enabled")) and setting.get("channel_id"):
        valid, _reason = log_service.validate_channel(
            guild,
            setting.get("channel_id"),
            needs_file=needs_file,
        )
        if valid:
            return None, False

    candidate = live_log_delivery_v5._discover_channel(guild, log_type)
    if candidate is None:
        return None, False

    await live_log_delivery_v5._repair_route(bot, guild, log_type, candidate)
    setting = await log_service.get_log_setting(bot, guild.id, log_type)
    return setting, True


async def send_log_v52(
    bot,
    guild: discord.Guild,
    log_type: str,
    embed: discord.Embed,
    file: discord.File | None = None,
    *,
    view: discord.ui.View | None = None,
    event_key: str | None = None,
) -> bool:
    """Compatibilité V5.3 : délègue directement au renderer Components V2."""
    state = _state(bot)
    state["attempts"] = int(state.get("attempts") or 0) + 1
    state.update({
        "last_guild_id": int(guild.id),
        "last_log_type": str(log_type),
        "last_channel_id": None,
        "last_result": None,
        "last_error": None,
        "last_error_message": None,
        "last_at": int(time.time()),
    })

    try:
        setting, recovered = await _resolve_setting(
            bot, guild, log_type, needs_file=file is not None
        )
        if setting is None:
            state["last_result"] = "disabled_or_no_route"
            return False

        channel_id = int(setting.get("channel_id") or 0)
        valid, reason = log_service.validate_channel(
            guild, channel_id, needs_file=file is not None
        )
        if not valid:
            state["last_result"] = "invalid_route"
            state["last_error_message"] = str(reason)[:300]
            return False

        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            state["last_result"] = "channel_missing"
            return False

        rendered = _render(embed)
        semantic_key = log_service.semantic_event_key(guild.id, log_type, rendered)
        if log_service._is_duplicate(event_key) or log_service._is_duplicate(semantic_key):
            state["last_channel_id"] = channel_id
            state["last_result"] = "duplicate"
            return False

        sent = await send_wide_log(
            channel,
            rendered,
            log_type=log_type,
            old_view=view,
            extra_file=file,
        )
        state["last_channel_id"] = channel_id
        state["last_result"] = "sent_v2" if sent else "v2_failed"
        if sent:
            state["sent"] = int(state.get("sent") or 0) + 1
            if recovered:
                state["recovered"] = int(state.get("recovered") or 0) + 1
        return bool(sent)
    except Exception as exc:
        state["last_result"] = "exception"
        state["last_error"] = type(exc).__name__
        state["last_error_message"] = str(exc)[:300]
        logger.exception("V5.3 compat : échec Components V2 guild=%s type=%s", guild.id, log_type)
        return False


def _patch_logs_cog(bot: commands.Bot) -> bool:
    """Retire un ancien override d'instance au lieu d'en poser un nouveau."""
    cog = bot.get_cog("Logs")
    if cog is None:
        _state(bot)["logs_send_patched"] = False
        return False

    if "_send" in vars(cog):
        stale = vars(cog).get("_send")
        function = getattr(stale, "__func__", stale)
        logger.warning(
            "V5.3 compat : ancien override Logs._send retiré | qualname=%s | module=%s",
            getattr(function, "__qualname__", "?"),
            getattr(function, "__module__", "?"),
        )
        delattr(cog, "_send")

    _state(bot)["logs_send_patched"] = False
    return True


def install(bot: commands.Bot) -> None:
    global _BOT
    _BOT = bot
    state = _state(bot)
    state["installed"] = True
    _patch_logs_cog(bot)
    logger.warning(
        "V5.3 compat chargé sans patch : transport officiel = log_service -> wide_logs."
    )


__all__ = [
    "install",
    "send_log_v52",
    "_patch_logs_cog",
    "_resolve_setting",
    "_render",
    "_unwrap_messageable_send",
    "_force_command_divider",
    "_force_sentrix_log_icon",
]
