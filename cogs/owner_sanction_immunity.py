"""Immunité de sanction pour le propriétaire du bot.

Le propriétaire vérifié de SentriX ne peut pas être ciblé par les sanctions manuelles,
les sanctions automatiques, le filtre multilingue ni l'anti-nuke de SentriX. Cette
protection concerne uniquement les actions exécutées par SentriX ; elle ne modifie pas
les permissions natives de Discord ou celles des autres bots.
"""
from __future__ import annotations

import logging

from discord.ext import commands

from utils import embeds
from utils.owner_access import is_bot_owner_id

logger = logging.getLogger("bot.owner-immunity")
_INSTALLED = False


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # Modération manuelle : ban/tempban/kick/mute/warn passent tous par check_targetable.
    try:
        from . import moderation
        original_targetable = moderation.Moderation.check_targetable

        async def check_targetable_protected(self, ctx, membre):
            if is_bot_owner_id(getattr(membre, "id", None)):
                await ctx.send(embed=embeds.error("Ce compte est protégé : SentriX ne peut pas le sanctionner."))
                return False
            return await original_targetable(self, ctx, membre)

        if not getattr(original_targetable, "_sentrix_owner_protection", False):
            check_targetable_protected._sentrix_owner_protection = True
            moderation.Moderation.check_targetable = check_targetable_protected
    except Exception:
        logger.exception("Protection propriétaire impossible sur le module de modération.")

    # AutoMod : le propriétaire ne doit subir ni suppression punitive, ni timeout,
    # ni escalade mute/kick/ban, même pour un mot blacklisté ou le dataset multilingue.
    try:
        from . import automod
        original_exempt = automod.AutoMod.is_automod_exempt
        original_escalate = automod.AutoMod._maybe_escalate
        original_delete_warn = automod.AutoMod._delete_and_warn
        original_delete_timeout = automod.AutoMod._delete_and_timeout
        original_antinuke_exempt = automod.AutoMod.is_antinuke_exempt
        original_punish_nuker = automod.AutoMod.punish_nuker

        async def is_automod_exempt_protected(self, member):
            if is_bot_owner_id(getattr(member, "id", None)):
                return True
            return await original_exempt(self, member)

        async def maybe_escalate_protected(self, guild, member, reason):
            if is_bot_owner_id(getattr(member, "id", None)):
                return None, 0
            return await original_escalate(self, guild, member, reason)

        async def delete_and_warn_protected(self, message, reason, filter_name="automod"):
            if is_bot_owner_id(getattr(message.author, "id", None)):
                return None
            return await original_delete_warn(self, message, reason, filter_name)

        async def delete_and_timeout_protected(self, message, reason, *, detection_kind):
            if is_bot_owner_id(getattr(message.author, "id", None)):
                return None
            return await original_delete_timeout(self, message, reason, detection_kind=detection_kind)

        async def antinuke_exempt_protected(self, guild, actor):
            if is_bot_owner_id(getattr(actor, "id", None)):
                return True
            return await original_antinuke_exempt(self, guild, actor)

        async def punish_nuker_protected(self, guild, actor_id, reason):
            if is_bot_owner_id(actor_id):
                logger.warning("Anti-nuke ignoré pour le propriétaire vérifié de SentriX sur %s.", guild.id)
                return None
            return await original_punish_nuker(self, guild, actor_id, reason)

        patches = (
            ("is_automod_exempt", original_exempt, is_automod_exempt_protected),
            ("_maybe_escalate", original_escalate, maybe_escalate_protected),
            ("_delete_and_warn", original_delete_warn, delete_and_warn_protected),
            ("_delete_and_timeout", original_delete_timeout, delete_and_timeout_protected),
            ("is_antinuke_exempt", original_antinuke_exempt, antinuke_exempt_protected),
            ("punish_nuker", original_punish_nuker, punish_nuker_protected),
        )
        for name, original, replacement in patches:
            if getattr(original, "_sentrix_owner_protection", False):
                continue
            replacement._sentrix_owner_protection = True
            setattr(automod.AutoMod, name, replacement)
    except Exception:
        logger.exception("Protection propriétaire impossible sur AutoMod.")

    _INSTALLED = True
    logger.info("Immunité complète de sanction du propriétaire SentriX activée.")
