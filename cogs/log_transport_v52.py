"""V5.3 — transport canonique final des logs SentriX.

Le diagnostic live a prouvé que les routes, intents et listeners étaient sains, mais qu'un
ancien wrapper pouvait encore remplacer ``log_service.send_log`` après l'installation de
V5.2. Cette version ne dépend donc plus de ce symbole global pour les vrais événements :
elle branche directement ``Logs._send`` sur le transport canonique.
"""
from __future__ import annotations

import logging
import time
import types
from typing import Any

import discord
from discord.ext import commands

from utils import embeds, log_service
from . import live_log_delivery_v5

logger = logging.getLogger("bot.log-transport-v53")
_MARKER = "_sentrix_log_transport_v53"


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
    state.setdefault("logs_send_patched", False)
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
    except Exception:
        # Un problème purement visuel ne doit jamais empêcher le journal métier de partir.
        logger.exception("V5.3 : normalisation incompatible ; embed original conservé.")
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

    # Une route valide mais explicitement désactivée reste volontairement désactivée.
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
    """Envoie un log sans repasser par la chaîne historique de wrappers send_log."""
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

        kwargs: dict[str, Any] = {
            "embed": rendered,
            "allowed_mentions": log_service.LOG_ALLOWED_MENTIONS,
        }
        if view is not None:
            kwargs["view"] = view
        if file is not None:
            kwargs["file"] = file

        # Appel au Messageable.send natif déballé : aucun wrapper SentriX de commande/log.
        native_send = _unwrap_messageable_send()
        await native_send(channel, **kwargs)

        state["last_channel_id"] = channel_id
        state["last_result"] = "sent_after_recovery" if recovered else "sent"
        state["sent"] = int(state.get("sent") or 0) + 1
        if recovered:
            state["recovered"] = int(state.get("recovered") or 0) + 1
        logger.info(
            "V5.3 log envoyé guild=%s type=%s channel=%s recovered=%s",
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
        logger.exception("V5.3 : échec transport log guild=%s type=%s", guild.id, log_type)
        return False


def _patch_logs_cog(bot: commands.Bot) -> bool:
    """Branche les 18 vrais listeners directement sur le transport canonique."""
    cog = bot.get_cog("Logs")
    if cog is None:
        _state(bot)["logs_send_patched"] = False
        return False

    current = getattr(cog, "_send", None)
    function = getattr(current, "__func__", current)
    if getattr(function, _MARKER, False):
        _state(bot)["logs_send_patched"] = True
        return True

    try:
        from .logs import CONFIG_TO_LOG_TYPE

        async def direct_logs_send(
            _self,
            guild: discord.Guild,
            config_key: str,
            embed: discord.Embed,
            *,
            view: discord.ui.View | None = None,
            event_key: str | None = None,
        ) -> bool:
            log_type = CONFIG_TO_LOG_TYPE.get(str(config_key))
            if log_type is None:
                return False
            return await send_log_v52(
                bot,
                guild,
                log_type,
                embed,
                view=view,
                event_key=event_key,
            )

        setattr(direct_logs_send, _MARKER, True)
        direct_logs_send._sentrix_original = function
        cog._send = types.MethodType(direct_logs_send, cog)
        _state(bot)["logs_send_patched"] = True
        logger.warning("V5.3 : Logs._send branché directement sur le transport canonique.")
        return True
    except Exception as exc:
        state = _state(bot)
        state["logs_send_patched"] = False
        state["last_error"] = type(exc).__name__
        state["last_error_message"] = str(exc)[:300]
        logger.exception("V5.3 : impossible de patcher Logs._send.")
        return False


def install(bot: commands.Bot) -> None:
    # Compatibilité : les producteurs qui appellent encore log_service passent aussi par V5.3.
    setattr(send_log_v52, _MARKER, True)
    log_service.send_log = send_log_v52
    state = _state(bot)
    state["installed"] = True
    _patch_logs_cog(bot)
    logger.info(
        "V5.3 actif : transport canonique + branchement direct des listeners Logs=%s.",
        state.get("logs_send_patched"),
    )


__all__ = ["install", "send_log_v52", "_patch_logs_cog"]
