"""Répare l'identification du serveur officiel SentriX.

La résolution d'une invitation Discord peut échouer ponctuellement même lorsque le bot est
bien présent dans le serveur cible. Cette couche utilise donc plusieurs preuves, de la plus
forte à la plus locale :
1. l'invitation officielle ;
2. le code d'invitation visible depuis le serveur courant ;
3. un appairage unique par structure du serveur officiel (Communauté + salons marqueurs) ;
4. les IDs persistants déjà enregistrés.

Dès qu'une preuve fiable est trouvée, l'ID du serveur et le salon d'annonces sont réparés
en base afin que les démarrages suivants ne dépendent plus d'une invitation temporairement
indisponible.
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
MARKER_CHANNELS = ("annonces-sentrix", "règlement")


async def _persist_binding(runtime, guild: discord.Guild) -> None:
    runtime._official_guild_id = guild.id
    await runtime._set_setting(OFFICIAL_GUILD_SETTING, guild.id)
    await runtime._set_setting(RELEASE_GUILD_SETTING, guild.id)

    channel = runtime._find_text(guild, "annonces-sentrix")
    if channel is not None:
        await runtime._set_setting(RELEASE_CHANNEL_SETTING, channel.id)


def _community_marker_match(runtime, guild: discord.Guild) -> bool:
    """Reconnaît la structure minimale du serveur d'aide officiel.

    On exige le mode Communauté ainsi que les deux salons conservés/configurés par
    l'installation officielle. Un simple serveur possédant un salon nommé annonces ne
    suffit donc pas à devenir la cible SentriX.
    """
    features = {str(feature).upper() for feature in getattr(guild, "features", ())}
    if "COMMUNITY" not in features:
        return False
    return all(runtime._find_text(guild, base_name) is not None for base_name in MARKER_CHANNELS)


def _unique_marker_guild(runtime) -> discord.Guild | None:
    matches = [guild for guild in runtime.bot.guilds if _community_marker_match(runtime, guild)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        logger.warning(
            "Appairage SentriX ambigu : %s serveurs Communauté possèdent les salons marqueurs.",
            len(matches),
        )
    return None


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
        logger.warning("Invitation officielle SentriX non résolue directement ; fallbacks locaux utilisés.")
    return None


async def official_guild_id_fixed(self) -> int | None:
    # 1) Source d'autorité : invitation officielle.
    resolved = await _resolve_invite_guild_id(self)
    if resolved:
        return resolved

    # 2) Si l'API d'invitation est indisponible, la structure officielle unique permet
    # de récupérer le bon serveur sans faire confiance à un ancien ID obsolète.
    marker_guild = _unique_marker_guild(self)
    if marker_guild is not None:
        await _persist_binding(self, marker_guild)
        logger.info(
            "Serveur officiel SentriX appairé via marqueurs Communauté : %s (%s)",
            marker_guild.name,
            marker_guild.id,
        )
        return marker_guild.id

    # 3) Fallback persistant uniquement si le serveur est encore réellement dans le cache.
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

    cached = getattr(self, "_official_guild_id", None)
    if cached and self.bot.get_guild(int(cached)) is not None:
        return int(cached)
    return None


async def is_official_guild_fixed(self, guild: discord.Guild) -> bool:
    # 1) Vérification la plus forte : le lien officiel pointe directement sur ce serveur.
    resolved = await _resolve_invite_guild_id(self)
    if resolved:
        return guild.id == resolved

    # 2) Vérifier le code de l'invitation depuis le serveur courant lorsque Discord le permet.
    try:
        invites = await guild.invites()
        if any(str(invite.code).casefold() == INVITE_CODE.casefold() for invite in invites):
            await _persist_binding(self, guild)
            logger.info("Serveur officiel SentriX réparé via code d'invitation : %s", guild.id)
            return True
    except (discord.Forbidden, discord.HTTPException):
        logger.info("Lecture des invitations indisponible pour le serveur %s ; fallback marqueurs.", guild.id)
    except Exception:
        logger.exception("Impossible de vérifier les invitations du serveur %s.", guild.id)

    # 3) Appairage structurel : seulement si ce serveur est l'unique serveur Communauté
    # du bot à posséder les deux salons marqueurs officiels.
    marker_guild = _unique_marker_guild(self)
    if marker_guild is not None and marker_guild.id == guild.id:
        await _persist_binding(self, guild)
        logger.info(
            "Serveur officiel SentriX auto-appairé via Communauté + salons marqueurs : %s",
            guild.id,
        )
        return True

    # 4) Dernier fallback : un ID persistant n'est accepté que s'il correspond au serveur courant.
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

    # Réinstaller même si une version plus ancienne de ce patch avait déjà posé son flag.
    # Cela permet aux hotfixes de remplacer les méthodes lors d'un reload sans redémarrage dur.
    runtime.official_guild_id = MethodType(official_guild_id_fixed, runtime)
    runtime.is_official_guild = MethodType(is_official_guild_fixed, runtime)
    runtime._sentrix_binding_fix = True
    runtime._sentrix_binding_fix_version = 2
    logger.info(
        "Détection serveur officiel SentriX V2 active : invitation + code + marqueurs Communauté + persistance."
    )


__all__ = ["install"]
