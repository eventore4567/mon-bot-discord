"""Compatibilité d'import uniquement.

Le moteur de logs est désormais canonique dans ``utils.log_service``. V83 ne doit plus
remplacer de fonction, de callback ou de transport au runtime.
"""
from __future__ import annotations

from discord.ext import commands


def install(bot: commands.Bot) -> None:
    return None


__all__ = ["install"]
