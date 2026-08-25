"""SentriX V71 — garde de sécurité transport pour les logs V70.

Cette couche ne change aucun rendu. Elle reste derrière le renderer V70 afin de conserver
les garanties métier de l'ancien pipeline : un seul service Railway publie, tentative de
réparation d'un salon de logs devenu invalide et déduplication des tickets qui utilisent
encore un salon dédié.
"""
from __future__ import annotations

import logging
import time
import types

import discord
from discord.ext import commands

from utils import log_service
from .log_rectangle_v25 import _is_primary_process

logger = logging.getLogger("bot.sentrix-log-safety-v71")
_INSTALLED = False
_TICKET_TTL = 15.0
_TICKET_RECENT: dict[str, float] = {}


def _prune_ticket_recent() -> None:
    now = time.monotonic()
    for key, expires in list(_TICKET_RECENT.items())[:3000]:
        if expires <= now:
            _TICKET_RECENT.pop(key, None)


def _ticket_key(guild: discord.Guild, source: discord.Embed) -> str:
    try:
        from . import log_dedupe_guard_v55 as v55
        return v55._source_key(guild, "tickets", source)
    except Exception:
        return f"{guild.id}:tickets:{source.title}:{source.description}"


async def _repair_if_needed(bot, guild: discord.Guild, log_type: str, file: discord.File | None) -> None:
    try:
        setting = await log_service.get_log_setting(bot, guild.id, str(log_type))
    except Exception:
        return
    if not setting.get("enabled"):
        return
    ok, _reason = log_service.validate_channel(
        guild,
        setting.get("channel_id"),
        needs_file=file is not None,
    )
    if ok:
        return
    try:
        from .moderation_logs_fix import _repair_log_target
        await _repair_log_target(bot, guild, str(log_type))
    except Exception:
        logger.debug(
            "V71 : réparation automatique du salon de logs impossible guild=%s type=%s.",
            guild.id,
            log_type,
            exc_info=True,
        )


def _patch_log_service() -> None:
    current = log_service.send_log
    if getattr(current, "_sentrix_log_safety_v71", False):
        return

    async def safe_send_log(
        bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        file: discord.File | None = None,
    ) -> bool:
        if not _is_primary_process():
            logger.debug(
                "V71 : log bloqué sur service secondaire guild=%s type=%s.",
                guild.id,
                log_type,
            )
            return False
        await _repair_if_needed(bot, guild, str(log_type), file)
        return bool(await current(bot, guild, str(log_type), embed, file=file))

    safe_send_log._sentrix_log_safety_v71 = True
    safe_send_log._sentrix_original = current
    log_service.send_log = safe_send_log


def _patch_ticket_direct_path(bot: commands.Bot) -> None:
    cog = bot.get_cog("Tickets")
    if cog is None or not hasattr(cog, "log_action"):
        return
    current = cog.log_action
    if getattr(current, "_sentrix_log_safety_v71", False):
        return

    async def safe_ticket_log(
        self,
        guild: discord.Guild,
        source: discord.Embed,
        log_channel_id: int | None = None,
    ):
        if not _is_primary_process():
            return None
        if not isinstance(source, discord.Embed):
            return await current(guild, source, log_channel_id)

        key = _ticket_key(guild, source)
        _prune_ticket_recent()
        if _TICKET_RECENT.get(key, 0.0) > time.monotonic():
            logger.debug("V71 : doublon ticket supprimé %s.", key)
            return None

        result = await current(guild, source, log_channel_id)
        _TICKET_RECENT[key] = time.monotonic() + _TICKET_TTL
        return result

    safe_ticket_log._sentrix_log_safety_v71 = True
    safe_ticket_log._sentrix_original = current
    cog.log_action = types.MethodType(safe_ticket_log, cog)


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    _patch_log_service()
    _patch_ticket_direct_path(bot)
    _INSTALLED = True
    logger.info("SentriX V71 : garde primaire, réparation de salon et déduplication ticket actives.")


__all__ = ["install"]
