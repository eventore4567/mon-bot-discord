"""Dernier garde-fou de +help V8.

Le bot nettoie certaines commandes APRES le chargement des extensions. Cette étape peut être
suivie de couches de localisation selon le contexte de démarrage. On garantit donc que le
callback V8 est réappliqué immédiatement après _prune_redundant_commands(), juste avant les
audits/sync de production.
"""
from __future__ import annotations

import logging
from types import MethodType

from discord.ext import commands

logger = logging.getLogger("bot.help-v8-final-guard")


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_help_v8_prune_guard", False):
        return
    prune = getattr(bot, "_prune_redundant_commands", None)
    if not callable(prune):
        return

    def prune_then_help(_bot, *args, **kwargs):
        result = prune(*args, **kwargs)
        try:
            from . import help_clean_style
            help_clean_style.install(_bot)
        except Exception:
            logger.exception("Impossible de réappliquer +help V8 après le nettoyage des commandes.")
        return result

    bot._prune_redundant_commands = MethodType(prune_then_help, bot)
    bot._sentrix_help_v8_prune_guard = True
    logger.info("Garde final +help V8 installé après le nettoyage des commandes.")
