"""Libère le verrou de concurrence slash V41 sans réinstaller de renderer/logger."""
from __future__ import annotations

import inspect
import logging

import discord
from discord.ext import commands

from .command_hardening_v41 import release_slash

logger = logging.getLogger("bot.command-error-release-v41")


def install(bot: commands.Bot) -> None:
    """Ajoute uniquement la libération du verrou slash en cas d'erreur.

    Le design Discord appartient à ``final_interaction_policy`` et les logs à
    ``utils.log_service``. Un handler d'erreur ne doit plus réinstaller un second
    transport ou un second logger.
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
    logger.info("V41 : verrou slash libéré sans couche runtime concurrente.")
