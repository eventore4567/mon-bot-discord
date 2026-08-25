"""Compatibilité historique de l'ancien garde +help V8.

Le rendu V8 n'est plus propriétaire de l'aide. `cogs.help_simple` est installé une seule
fois lors de la finalisation du runtime et ne doit jamais être réécrit après le pruning.
Ce module reste importable afin de ne pas casser d'anciens imports, mais n'enveloppe plus
`_prune_redundant_commands` et n'appelle plus de renderer historique.
"""
from __future__ import annotations

import logging
from discord.ext import commands

logger = logging.getLogger("bot.help-v8-final-guard")


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_help_v8_compat_disabled", False):
        return
    bot._sentrix_help_v8_compat_disabled = True
    logger.info("Ancien garde +help V8 neutralisé ; cogs.help_simple reste propriétaire de l'aide.")


__all__ = ["install"]
