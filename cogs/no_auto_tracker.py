"""Empêche +create-server et sa migration de publier +suivi-bot automatiquement.

Le cog BotTracker et la commande +suivi-bot restent disponibles. Seule la publication
automatique dans #annonces est désactivée : un panneau n'existe que lorsqu'un admin lance
explicitement +suivi-bot.
"""
from __future__ import annotations

import logging

from discord.ext import commands

logger = logging.getLogger("bot.no-auto-tracker")
_INSTALLED = False


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import server_builder_ready_setup as ready

    original = ready._ensure_announcements
    if getattr(original, "_sentrix_no_auto_tracker", False):
        _INSTALLED = True
        return

    async def ensure_announcements_without_tracker(bot_obj, builder_cog, guild, channel, creator_id):
        # Conserve uniquement la présentation SentriX. Aucun panneau de suivi n'est créé,
        # enregistré ou déplacé automatiquement.
        await builder_cog._publish_once(
            channel,
            "SentriX • Présentation automatique v1",
            ready._bot_ready_embed(guild),
        )
        return "présentation SentriX installée • suivi-bot uniquement sur commande"

    ensure_announcements_without_tracker._sentrix_no_auto_tracker = True
    ready._ensure_announcements = ensure_announcements_without_tracker
    _INSTALLED = True
    logger.info("Publication automatique de +suivi-bot désactivée ; commande manuelle conservée.")
