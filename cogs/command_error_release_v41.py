"""Libère toujours les verrous V41 lorsqu'une commande slash échoue.

Cette couche est aussi le dernier point de finition du runtime : elle réapplique la surface
slash, puis verrouille l'aide compacte sans embed et le renderer de logs à taille fixe.
"""
from __future__ import annotations

import asyncio
import inspect
import logging

import discord
from discord.ext import commands

from .command_hardening_v41 import release_slash

logger = logging.getLogger("bot.command-error-release-v41")


def _install_final_surfaces(bot: commands.Bot) -> None:
    # Catalogue slash : anciennes / utiles prioritaires, + uniquement dans les places restantes.
    try:
        from .user_command_final_v64 import install as install_user_command_final_v64
        install_user_command_final_v64(bot)
    except Exception:
        logger.exception("V64 : impossible d'installer la surface finale des commandes.")

    # V65 DOIT passer après V64 et toutes les anciennes couches help.
    try:
        from .help_plain_compact_v65 import install as install_help_plain_compact_v65
        install_help_plain_compact_v65(bot)
    except Exception:
        logger.exception("V65 : impossible d'installer l'aide compacte finale.")

    # V56 DOIT passer après V30/V50/V53/V55 : un seul renderer de logs reste actif.
    try:
        from .log_fixed_compact_v56 import install as install_log_fixed_compact_v56
        install_log_fixed_compact_v56(bot)
    except Exception:
        logger.exception("V56 : impossible de verrouiller la taille finale des logs.")


def _install_ready_reassert(bot: commands.Bot) -> None:
    """Réaffirme une dernière fois les deux surfaces après tous les hooks on_ready."""
    if getattr(bot, "_sentrix_final_surfaces_ready_listener", False):
        return

    async def reassert_final_surfaces():
        # Laisse terminer les autres listeners on_ready de ce cycle, puis reprend la priorité.
        await asyncio.sleep(0)
        _install_final_surfaces(bot)

    bot.add_listener(reassert_final_surfaces, "on_ready")
    bot._sentrix_final_surfaces_ready_listener = True


def install(bot: commands.Bot) -> None:
    # V3.8 reste la passe qualité/sécurité historique.
    try:
        from .sentrix_final_quality_v38 import install as install_final_quality_v38
        install_final_quality_v38(bot)
    except Exception:
        logger.exception("V3.8 : impossible d'installer la passe finale qualité/sécurité.")

    _install_final_surfaces(bot)
    _install_ready_reassert(bot)

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
    logger.info("V41 : concurrence slash libérée, help V65 et logs V56 verrouillés en dernier.")
