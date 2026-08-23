"""SentriX V31 — unification des catégories de logs.

Certains tickets configurés avec un salon dédié utilisaient encore directement
``channel.send(embed=...)`` et contournaient donc V27/V28/V30. Cette couche conserve le
salon dédié choisi par l'administrateur, mais rend l'événement avec le même Components V2
que les logs messages. Le fallback reste le log_service central.
"""
from __future__ import annotations

import logging
import types

import discord
from discord.ext import commands

from utils import log_service
from . import premium_logs_v2
from .premium_logs import style_log, _button_items

logger = logging.getLogger("bot.log-category-unifier-v31")


async def _send_preferred(
    bot: commands.Bot,
    channel,
    guild: discord.Guild,
    log_type: str,
    embed: discord.Embed,
) -> bool:
    """Envoie un log via le renderer final actuellement installé (V30+)."""
    try:
        styled = style_log(bot, guild, log_type, embed.copy())
        buttons = _button_items(styled, str(styled.title or ""))
        layout = premium_logs_v2.PremiumLogLayout(bot, guild, log_type, styled, buttons)
        await channel.send(
            view=layout,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False
    except Exception:
        logger.exception("V31 : rendu premium direct impossible guild=%s type=%s", guild.id, log_type)
        return False


def _patch_tickets(bot: commands.Bot) -> None:
    cog = bot.get_cog("Tickets")
    if cog is None or not hasattr(cog, "log_action"):
        return
    current = cog.log_action
    if getattr(current, "_sentrix_category_unifier_v31", False):
        return

    async def unified_log_action(self, guild: discord.Guild, embed: discord.Embed, log_channel_id: int | None = None):
        # Le salon dédié reste prioritaire, mais il reçoit désormais EXACTEMENT le même
        # renderer final que logs-messages au lieu d'un vieux embed Discord vertical.
        if log_channel_id:
            channel = guild.get_channel(int(log_channel_id))
            if channel is not None and await _send_preferred(self.bot, channel, guild, "tickets", embed):
                return

        # Sans salon dédié, ou si Discord refuse l'envoi direct, on conserve tout le
        # pipeline central : routage /logsetup, déduplication, audit et renderer final.
        await log_service.send_log(self.bot, guild, "tickets", embed)

    unified_log_action._sentrix_category_unifier_v31 = True
    unified_log_action._sentrix_original = current
    cog.log_action = types.MethodType(unified_log_action, cog)
    logger.info("V31 : Tickets.log_action unifié avec le renderer premium final.")


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del extension_name
    _patch_tickets(bot)


__all__ = ["install"]
