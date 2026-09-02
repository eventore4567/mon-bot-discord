"""Immunité de sanction pour le propriétaire vérifié de SentriX.

Le compte propriétaire de SentriX ne peut pas être ciblé par les sanctions exécutées par
SentriX. La protection existe à deux niveaux :
- commandes/runtimes (modération, AutoMod, anti-nuke) ;
- garde bas niveau discord.py pour ban, kick et timeout, même si un autre module appelle
  directement les méthodes Discord au lieu de passer par les commandes de modération.

Cette protection ne change pas les permissions natives Discord et ne peut pas empêcher un
autre bot ou un humain distinct de sanctionner ce compte.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels
from utils.owner_access import is_bot_owner_id

logger = logging.getLogger("bot.owner-immunity")
_INSTALLED = False
_HARD_GUARD_INSTALLED = False


def _is_protected(target) -> bool:
    return is_bot_owner_id(getattr(target, "id", target if isinstance(target, int) else None))


def _install_discord_api_guard() -> None:
    """Bloque les sanctions avant l'appel HTTP Discord.

    Les wrappers sont posés sur les API publiques discord.py utilisées par les cogs. Ils
    sont idempotents afin que l'installation puisse être rappelée après chaque extension.
    Une levée de timeout (``until=None``) reste autorisée.
    """
    global _HARD_GUARD_INSTALLED
    if _HARD_GUARD_INSTALLED:
        return

    original_guild_ban = discord.Guild.ban
    if not getattr(original_guild_ban, "_sentrix_owner_hard_guard", False):
        async def guild_ban_protected(self, user, *args, **kwargs):
            if _is_protected(user):
                logger.warning(
                    "BAN BLOQUÉ : SentriX a refusé de bannir son propriétaire vérifié sur guild=%s.",
                    self.id,
                )
                return None
            return await original_guild_ban(self, user, *args, **kwargs)

        guild_ban_protected._sentrix_owner_hard_guard = True
        guild_ban_protected._sentrix_original = original_guild_ban
        discord.Guild.ban = guild_ban_protected

    original_guild_kick = discord.Guild.kick
    if not getattr(original_guild_kick, "_sentrix_owner_hard_guard", False):
        async def guild_kick_protected(self, user, *args, **kwargs):
            if _is_protected(user):
                logger.warning(
                    "KICK BLOQUÉ : SentriX a refusé d'expulser son propriétaire vérifié sur guild=%s.",
                    self.id,
                )
                return None
            return await original_guild_kick(self, user, *args, **kwargs)

        guild_kick_protected._sentrix_owner_hard_guard = True
        guild_kick_protected._sentrix_original = original_guild_kick
        discord.Guild.kick = guild_kick_protected

    if hasattr(discord.Member, "ban"):
        original_member_ban = discord.Member.ban
        if not getattr(original_member_ban, "_sentrix_owner_hard_guard", False):
            async def member_ban_protected(self, *args, **kwargs):
                if _is_protected(self):
                    logger.warning(
                        "BAN MEMBRE BLOQUÉ : cible propriétaire SentriX guild=%s.",
                        self.guild.id,
                    )
                    return None
                return await original_member_ban(self, *args, **kwargs)

            member_ban_protected._sentrix_owner_hard_guard = True
            member_ban_protected._sentrix_original = original_member_ban
            discord.Member.ban = member_ban_protected

    if hasattr(discord.Member, "kick"):
        original_member_kick = discord.Member.kick
        if not getattr(original_member_kick, "_sentrix_owner_hard_guard", False):
            async def member_kick_protected(self, *args, **kwargs):
                if _is_protected(self):
                    logger.warning(
                        "KICK MEMBRE BLOQUÉ : cible propriétaire SentriX guild=%s.",
                        self.guild.id,
                    )
                    return None
                return await original_member_kick(self, *args, **kwargs)

            member_kick_protected._sentrix_owner_hard_guard = True
            member_kick_protected._sentrix_original = original_member_kick
            discord.Member.kick = member_kick_protected

    if hasattr(discord.Member, "timeout"):
        original_timeout = discord.Member.timeout
        if not getattr(original_timeout, "_sentrix_owner_hard_guard", False):
            async def timeout_protected(self, until, *args, **kwargs):
                if _is_protected(self) and until is not None:
                    logger.warning(
                        "TIMEOUT BLOQUÉ : cible propriétaire SentriX guild=%s.",
                        self.guild.id,
                    )
                    return None
                return await original_timeout(self, until, *args, **kwargs)

            timeout_protected._sentrix_owner_hard_guard = True
            timeout_protected._sentrix_original = original_timeout
            discord.Member.timeout = timeout_protected

    original_member_edit = discord.Member.edit
    if not getattr(original_member_edit, "_sentrix_owner_hard_guard", False):
        async def member_edit_protected(self, *args, **kwargs):
            if _is_protected(self) and kwargs.get("timed_out_until") is not None:
                logger.warning(
                    "TIMEOUT VIA EDIT BLOQUÉ : cible propriétaire SentriX guild=%s.",
                    self.guild.id,
                )
                kwargs = dict(kwargs)
                kwargs.pop("timed_out_until", None)
                if not kwargs:
                    return self
            return await original_member_edit(self, *args, **kwargs)

        member_edit_protected._sentrix_owner_hard_guard = True
        member_edit_protected._sentrix_original = original_member_edit
        discord.Member.edit = member_edit_protected

    _HARD_GUARD_INSTALLED = True
    logger.info("Verrou bas niveau ban/kick/timeout du propriétaire SentriX activé.")


def install(bot: commands.Bot) -> None:
    global _INSTALLED

    _install_discord_api_guard()

    if _INSTALLED:
        return

    try:
        from . import moderation
        original_targetable = moderation.Moderation.check_targetable

        async def check_targetable_protected(self, ctx, membre):
            if is_bot_owner_id(getattr(membre, "id", None)):
                await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Ce compte est protégé : SentriX ne peut pas le sanctionner.')))
                return False
            return await original_targetable(self, ctx, membre)

        if not getattr(original_targetable, "_sentrix_owner_protection", False):
            check_targetable_protected._sentrix_owner_protection = True
            moderation.Moderation.check_targetable = check_targetable_protected
    except Exception:
        logger.exception("Protection propriétaire impossible sur le module de modération.")

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


# cogs.__init__ importe ce module avant le chargement des extensions : le garde public
# discord.py est donc actif immédiatement, même avant le Cog de modération.
_install_discord_api_guard()


__all__ = ["install"]
