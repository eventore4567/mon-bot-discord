"""Libère toujours les verrous V41 lorsqu'une commande slash échoue.

final_interaction_policy réinstalle le gestionnaire d'erreurs après chaque extension. Cette
petite couche se place juste après lui et enveloppe le handler final sans modifier le texte
d'erreur envoyé à l'utilisateur.
"""
from __future__ import annotations

import inspect
import logging

import discord
from discord.ext import commands

from .command_hardening_v41 import release_slash

logger = logging.getLogger("bot.command-error-release-v41")


def install(bot: commands.Bot) -> None:
    current = bot.tree.on_error
    if getattr(current, "_sentrix_v41_release", False):
        return

    async def error_with_release(
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ):
        release_slash(interaction)
        result = current(interaction, error)
        if inspect.isawaitable(result):
            return await result
        return result

    error_with_release._sentrix_v41_release = True
    error_with_release._sentrix_previous = current
    bot.tree.on_error = error_with_release
    logger.info("V41 : libération des limites de concurrence slash sur erreur activée.")
