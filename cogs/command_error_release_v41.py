"""Libère le verrou de concurrence slash V41, sans modifier l'interface Discord."""
from __future__ import annotations

import inspect
import logging

import discord
from discord.ext import commands

from .command_hardening_v41 import release_slash

logger = logging.getLogger("bot.command-error-release-v41")


def install(bot: commands.Bot) -> None:
    """Ajoute uniquement la libération du verrou en cas d'erreur slash.

    Les anciens installateurs visuels V64/V70/V71/V72 ont été retirés d'ici : un handler
    d'erreur ne doit jamais réinstaller un second help, un second renderer ou un second
    logger au démarrage/on_ready.
    """
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
    logger.info("V41 : verrou slash libéré sans couche visuelle supplémentaire.")
