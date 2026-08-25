"""Libère les verrous V41 et applique la finition visuelle finale SentriX."""
from __future__ import annotations

import asyncio
import inspect
import logging

import discord
from discord.ext import commands

from .command_hardening_v41 import release_slash

logger = logging.getLogger("bot.command-error-release-v41")


def _install_final_surfaces(bot: commands.Bot) -> None:
    # Le catalogue de commandes reste séparé de la présentation : les anciennes /
    # utiles sont prioritaires et les + remplissent seulement les places restantes.
    try:
        from .user_command_final_v64 import install as install_user_command_final_v64
        install_user_command_final_v64(bot)
    except Exception:
        logger.exception("V64 : impossible d'installer la surface finale des commandes.")

    # Une seule couche visuelle générale finale.
    try:
        from .sentrix_visual_refactor_v70 import install as install_sentrix_visual_refactor_v70
        install_sentrix_visual_refactor_v70(bot)
    except Exception:
        logger.exception("V70 : impossible d'installer la refonte visuelle finale.")

    # Le profil possède une organisation métier spécifique (Compte / Serveur / Économie /
    # Activité) mais utilise exactement la même fabrique d'embed V70.
    try:
        from .sentrix_profile_refactor_v70 import install as install_sentrix_profile_refactor_v70
        install_sentrix_profile_refactor_v70(bot)
    except Exception:
        logger.exception("V70 : impossible d'installer la présentation du profil.")


def _install_ready_reassert(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_final_surfaces_ready_listener", False):
        return

    async def reassert_final_surfaces():
        await asyncio.sleep(0)
        _install_final_surfaces(bot)

    bot.add_listener(reassert_final_surfaces, "on_ready")
    bot._sentrix_final_surfaces_ready_listener = True


def install(bot: commands.Bot) -> None:
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
    logger.info("V41 : concurrence slash libérée, refonte visuelle V70 appliquée en dernier.")
