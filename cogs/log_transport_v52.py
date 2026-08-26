"""V5.2 — transport canonique final des logs SentriX.

Les anciens renderers ont empilé plusieurs wrappers autour de ``log_service.send_log``.
Le diagnostic live a montré un TypeError dans cette chaîne alors que les routes, intents et
listeners étaient valides. Cette couche remplace donc toute la chaîne par UNE sortie :
route -> validation -> normalisation -> déduplication -> envoi Discord natif.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import discord
from discord.ext import commands

from utils import embeds, log_service
from . import live_log_delivery_v5

logger = logging.getLogger("bot.log-transport-v52")
_MARKER = "_sentrix_log_transport_v52"


def _state(bot: commands.Bot) -> dict[str, Any]:
    state = getattr(bot, "log_transport_v52_state", None)
    if not isinstance(state, dict):
        state = {
            "installed": False,
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
    return state


def _unwrap_messageable_send():
    current = discord.abc.Messageable.send
    seen: set[int] = set()
    while hasattr(current, "_sentrix_original") and id(current) not in seen:
        seen.add(id(current))
        current = getattr(current, "_sentrix_original")
    return current


def _render(embed: discord.Embed) -> discord.Embed:
    if not isinstance(embed, discord.Embed):
        return embed
    try:
        return embeds.normalize_log(embed)
    except TypeError:
        # Un ancien renderer peut avoir une signature incompatible. Le log métier fourni
        # par cogs.logs est déjà un discord.Embed valide : ne jamais bloquer l'envoi pour
        # un problème purement visuel.
        logger.exception("V5.2 : normalisation historique incompatible ; embed original conservé.")
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

    # Une route valide mais explicitement désactivée reste désactivée.
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
        if channel is None:
            state["last_result"] = "channel_missing"
            return False

        rendered = _render(embed)
        semantic_key = log_service.semantic_event_key(guild.id, log_type, rendered)
        if log_service._is_duplicate(event_key) or log_service._is_duplicate(semantic_key):
            state["last_channel_id"] = channel_id
            state["last_result"] = "duplicate"
            return False

        kwargs = {
            "embed": rendered,
            "allowed_mentions": log_service.LOG_ALLOWED_MENTIONS,
        }
        if view is not None:
            kwargs["view"] = view
        if file is not None:
            kwargs["file"] = file

        # Appel direct au Messageable.send de discord.py, sans les wrappers de commandes.
        native_send = _unwrap_messageable_send()
        await native_send(channel, **kwargs)

        state["last_channel_id"] = channel_id
        state["last_result"] = "sent_after_recovery" if recovered else "sent"
        state["sent"] = int(state.get("sent") or 0) + 1
        if recovered:
            state["recovered"] = int(state.get("recovered") or 0) + 1
        logger.info(
            "V5.2 log envoyé guild=%s type=%s channel=%s recovered=%s",
            guild.id,
            log_type,
            channel_id,
            recovered,
        )
        return True
    except Exception as exc:
        state["last_result"] = "exception"
        state["last_error"] = type(exc).__name__
        state["last_error_message"] = str(exc)[:300]
        logger.exception("V5.2 : échec transport log guild=%s type=%s", guild.id, log_type)
        return False


def install(bot: commands.Bot) -> None:
    send_log_v52._sentrix_log_transport_v52 = True
    log_service.send_log = send_log_v52
    state = _state(bot)
    state["installed"] = True
    logger.info("V5.2 actif : transport logs canonique sans chaîne de wrappers legacy.")


__all__ = ["install", "send_log_v52"]
