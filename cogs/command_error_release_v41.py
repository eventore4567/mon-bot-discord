"""Compatibilité de l'ancien verrou d'erreur V41.

La libération des limites slash est maintenant intégrée directement à
``cogs.command_error_policy`` et au refus de ``permission_guard``. Aucun handler d'erreur
supplémentaire n'est donc empilé ici.
"""
from __future__ import annotations

from discord.ext import commands


def install(bot: commands.Bot) -> None:
    from .command_error_policy import install as install_error_policy
    install_error_policy(bot)
    bot._sentrix_v41_release_integrated = True


__all__ = ["install"]
