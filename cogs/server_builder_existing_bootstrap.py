"""Applique la nouvelle configuration prête à l'emploi aux structures SentriX existantes."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

logger = logging.getLogger("bot.server-builder.bootstrap")
_INSTALLED = False


async def _bootstrap(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    # Laisse les derniers cogs (économie, stats, etc.) terminer leur chargement.
    await asyncio.sleep(3)

    from . import server_builder
    from . import server_builder_ready_setup as ready

    builder = bot.get_cog("ServerBuilder")
    if builder is None:
        return

    for guild in list(bot.guilds):
        choice = ready._find_text_channel(server_builder, guild, "ACCUEIL", "choix-des-rôles")
        shop = ready._find_text_channel(server_builder, guild, "ÉCONOMIE", "boutique")
        announcements = ready._find_text_channel(server_builder, guild, "ACCUEIL", "annonces")
        # Ne modifie pas un serveur quelconque : il faut reconnaître les trois salons
        # principaux de la structure générée par +create-server.
        if choice is None or shop is None or announcements is None:
            continue

        try:
            current = choice.overwrites_for(guild.default_role)
            current.send_messages = False
            current.add_reactions = False
            current.create_public_threads = False
            current.create_private_threads = False
            current.send_messages_in_threads = False
            await choice.set_permissions(
                guild.default_role,
                overwrite=current,
                reason="SentriX : salon choix-des-rôles en lecture seule",
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Impossible de verrouiller choix-des-rôles sur %s", guild.id)

        author = guild.owner
        if author is None:
            try:
                author = await guild.fetch_member(guild.owner_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                author = None
        if author is None:
            continue

        try:
            await ready._finish_ready_setup(bot, builder, guild, author)
            logger.info("Structure SentriX existante migrée sur %s (%s).", guild.name, guild.id)
        except Exception:
            logger.exception("Migration automatique de la structure SentriX impossible sur %s", guild.id)


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    asyncio.create_task(_bootstrap(bot), name="sentrix-existing-server-bootstrap")
