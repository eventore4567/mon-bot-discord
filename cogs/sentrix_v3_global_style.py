"""Compatibilité de l'ancien nom ``sentrix_v3_global_style``.

Le rendu des commandes n'est plus monkey-patché ici. La source canonique est désormais
``utils.command_ui_policy`` et le seul transport qui l'appelle est
``cogs.final_interaction_policy``. Ce module conserve uniquement l'installation du pack
d'emojis afin de ne casser aucun import historique.
"""
from __future__ import annotations

import logging

from discord.ext import commands

logger = logging.getLogger("bot.sentrix-style-compat")


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_ui_policy_registered", False):
        return
    try:
        from .sentrix_emoji_runtime import install as install_animated_emoji_pack
        install_animated_emoji_pack(bot)
    except Exception:
        logger.exception("Impossible d'installer le pack d'emojis SentriX.")
    bot._sentrix_ui_policy_registered = True
    logger.info("Style SentriX canonique : utils.command_ui_policy (aucun monkey-patch V3).")


__all__ = ["install"]
