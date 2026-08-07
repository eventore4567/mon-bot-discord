"""Immunité de sanction pour le propriétaire du bot.

Le propriétaire configuré dans OWNER_IDS ne peut pas être ciblé par les sanctions
manuelles de SentriX ni par l'escalade AutoMod. Cette protection concerne uniquement
les actions exécutées par SentriX ; elle ne modifie pas les permissions natives Discord.
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

    # AutoMod : aucune suppression/escalade ne doit cibler le propriétaire du bot.
    try:
        from . import automod
        original_exempt = automod.AutoMod.is_automod_exempt
        original_escalate = automod.AutoMod._maybe_escalate

        async def is_automod_exempt_protected(self, member):
            if is_bot_owner_id(getattr(member, "id", None)):
                return True
            return await original_exempt(self, member)

        async def maybe_escalate_protected(self, guild, member, reason):
            if is_bot_owner_id(getattr(member, "id", None)):
                return None, 0
            return await original_escalate(self, guild, member, reason)

        if not getattr(original_exempt, "_sentrix_owner_protection", False):
            is_automod_exempt_protected._sentrix_owner_protection = True
            automod.AutoMod.is_automod_exempt = is_automod_exempt_protected
        if not getattr(original_escalate, "_sentrix_owner_protection", False):
            maybe_escalate_protected._sentrix_owner_protection = True
            automod.AutoMod._maybe_escalate = maybe_escalate_protected
    except Exception:
        logger.exception("Protection propriétaire impossible sur AutoMod.")

    _INSTALLED = True
    logger.info("Immunité de sanction du propriétaire SentriX activée.")
