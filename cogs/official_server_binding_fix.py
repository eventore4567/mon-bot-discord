"""Répare l'identification du serveur officiel SentriX.

L'ancien runtime faisait confiance en priorité à un ID persistant pouvant devenir obsolète.
Ce correctif donne la priorité à l'invitation officielle et sait également reconnaître le
serveur courant via son propre catalogue d'invitations. Lorsqu'une correspondance est
trouvée, les paramètres persistants sont réparés automatiquement.
"""
from __future__ import annotations

import logging
from types import MethodType

import discord
from discord.ext import commands

from .official_server import (
    OFFICIAL_GUILD_SETTING,
    OFFICIAL_INVITE,
    RELEASE_CHANNEL_SETTING,
    RELEASE_GUILD_SETTING,
)

logger = logging.getLogger("bot.official-server-binding-fix")
INVITE_CODE = OFFICIAL_INVITE.rstrip("/").rsplit("/", 1)[-1]


async def _persist_binding(runtime, guild: discord.Guild) -> None:
    runtime._official_guild_id = guild.id
    await runtime._set_setting(OFFICIAL_GUILD_SETTING, guild.id)
    await runtime._set_setting(RELEASE_GUILD_SETTING, guild.id)

    channel = runtime._find_text(guild, "annonces-sentrix")
    if channel is not None:
        await runtime._set_setting(RELEASE_CHANNEL_SETTING, channel.id)


async def _resolve_invite_guild_id(runtime) -> int | None:
    try:
        invite = await runtime.bot.fetch_invite(OFFICIAL_INVITE, with_counts=False)
        guild_id = getattr(getattr(invite, "guild", None), "id", None)
        if guild_id:
            guild_id = int(guild_id)
            runtime._official_guild_id = guild_id
            await runtime._set_setting(OFFICIAL_GUILD_SETTING, guild_id)
            await runtime._set_setting(RELEASE_GUILD_SETTING, guild_id)
            guild = runtime.bot.get_guild(guild_id)
            if guild is not None:
                channel = runtime._find_text(guild, "annonces-sentrix")
                if channel is not None:
                    await runtime._set_setting(RELEASE_CHANNEL_SETTING, channel.id)
            return guild_id
    except Exception:
        logger.warning("Invitation officielle SentriX non résolue directement ; fallback local utilisé.")
    return None


async def official_guild_id_fixed(self) -> int | None:
    # L'invitation est la source d'autorité. Elle corrige automatiquement un ancien ID
    # enregistré par une ancienne version du bot.
    resolved = await _resolve_invite_guild_id(self)
    if resolved:
        return resolved

    # Fallback seulement si Discord ne permet momentanément pas de résoudre l'invitation.
    for key in (OFFICIAL_GUILD_SETTING, RELEASE_GUILD_SETTING):
        raw = await self._get_setting(key)
        if not raw:
            continue
        try:
            guild_id = int(raw)
        except (TypeError, ValueError):
            continue
        if self.bot.get_guild(guild_id) is not None:
            self._official_guild_id = guild_id
            return guild_id

    # Le cache mémoire n'est accepté qu'il correspond encore à un serveur où le bot est présent.
    cached = getattr(self, "_official_guild_id", None)
    if cached and self.bot.get_guild(int(cached)) is not None:
        return int(cached)
    return None


async def is_official_guild_fixed(self, guild: discord.Guild) -> bool:
    # 1) Vérification la plus fiable : le lien officiel pointe directement sur ce serveur.
    resolved = await _resolve_invite_guild_id(self)
    if resolved:
        return guild.id == resolved

    # 2) Si l'endpoint d'invitation échoue, vérifier les invitations du serveur courant.
    # +sentrix-server exige déjà Administrateur, donc SentriX peut normalement les lire.
    try:
        invites = await guild.invites()
        if any(str(invite.code).casefold() == INVITE_CODE.casefold() for invite in invites):
            await _persist_binding(self, guild)
            logger.info("Serveur officiel SentriX réparé via code d'invitation : %s", guild.id)
            return True
    except (discord.Forbidden, discord.HTTPException):
        pass
    except Exception:
        logger.exception("Impossible de vérifier les invitations du serveur %s.", guild.id)

    # 3) Dernier fallback : un ID persistant n'est accepté que s'il correspond au serveur courant.
    for key in (OFFICIAL_GUILD_SETTING, RELEASE_GUILD_SETTING):
        raw = await self._get_setting(key)
        if not raw:
            continue
        try:
            if int(raw) == guild.id:
                await _persist_binding(self, guild)
                return True
        except (TypeError, ValueError):
            continue
    return False


def install(bot: commands.Bot) -> None:
    runtime = getattr(bot, "_sentrix_official_server_runtime", None)
    if runtime is None:
        return
    if getattr(runtime, "_sentrix_binding_fix", False):
        return

    runtime.official_guild_id = MethodType(official_guild_id_fixed, runtime)
    runtime.is_official_guild = MethodType(is_official_guild_fixed, runtime)
    runtime._sentrix_binding_fix = True
    logger.info("Détection du serveur officiel SentriX réparée : invitation prioritaire + auto-réparation.")


__all__ = ["install"]
