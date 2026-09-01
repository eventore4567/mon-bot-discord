"""Compatibilité d'import uniquement.

Le routage V85 a été intégré dans ``utils.log_categories`` et ``utils.log_service``.
Aucun monkey-patch ne doit être installé depuis ce module.
"""
from __future__ import annotations

from discord.ext import commands


def install(bot: commands.Bot) -> None:
    return None


__all__ = ["install"]
