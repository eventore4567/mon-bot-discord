"""Maintient la structure SentriX existante sans republier les annonces au redémarrage."""
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
    from .security_runtime_hardening import apply_recommended_security

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

        # Au redémarrage, on entretient uniquement la configuration technique.
        # IMPORTANT : on ne republie plus l'annonce ni le panneau +suivi-bot. Ceux-ci
        # ne sont créés que lors du premier +create-server ou sur demande explicite.
        try:
            await ready._ensure_role_panels(bot, guild, choice, author.id)
        except Exception:
            logger.exception("Migration des panneaux de rôles impossible sur %s", guild.id)
        try:
            await ready._ensure_shop(bot, guild, shop, author.id)
        except Exception:
            logger.exception("Migration de la boutique impossible sur %s", guild.id)
        try:
            await apply_recommended_security(bot, guild)
        except Exception:
            logger.exception("Migration de la sécurité impossible sur %s", guild.id)
        try:
            await ready._cleanup_old_generated_channels(server_builder, guild)
        except Exception:
            logger.exception("Nettoyage de structure impossible sur %s", guild.id)

        logger.info(
            "Structure SentriX entretenue sur %s (%s), sans republication annonce/suivi.",
            guild.name,
            guild.id,
        )


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    asyncio.create_task(_bootstrap(bot), name="sentrix-existing-server-bootstrap")
