"""Libère le verrou de concurrence slash et verrouille le contrat runtime final."""
from __future__ import annotations

import inspect
import logging

import discord
from discord.ext import commands

from .command_hardening_v41 import release_slash
from .runtime_contract_final import install as install_runtime_contract_final

logger = logging.getLogger("bot.command-error-release-v41")


def install(bot: commands.Bot) -> None:
    """Installe le contrat final puis conserve la libération du verrou slash."""
    # Cette étape est volontairement exécutée avant le garde ci-dessous : même si le
    # handler d'erreur est déjà installé, le contrat logs/embeds doit toujours l'être.
    install_runtime_contract_final(bot)

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
    logger.info("V41 : verrou slash libéré et contrat runtime final appliqué.")
