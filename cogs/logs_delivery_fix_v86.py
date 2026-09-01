"""Compatibilité d'import uniquement.

La validation de livraison est désormais faite directement par ``utils.log_service``.
Ce module ne modifie plus aucune méthode au runtime.
"""
from __future__ import annotations

from discord.ext import commands


def install(bot: commands.Bot) -> None:
    return None


__all__ = ["install"]
