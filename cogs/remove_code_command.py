"""Compatibilité historique du loader IA et catalogue complet des commandes."""

from __future__ import annotations

import logging

from discord.ext import commands

from .command_catalog_cleanup import install as install_command_catalog_cleanup
from .operations_center import install as install_operations_center

logger = logging.getLogger("bot.remove-code-command")
_INSTALLED = False


async def install(bot: commands.Bot) -> None:
    """Applique le catalogue canonique, Operations et conserve +code comme commande utile."""
    # Cette fonction est appelée pendant le chargement du cog IA, donc avant le pruning
    # final de main.setup_hook(). À ce moment AutoMod/Tickets/Configuration sont déjà
    # chargés : Operations peut brancher ses checks, diagnostics et scopes sans ajouter
    # de nouvelle commande publique au catalogue.
    install_command_catalog_cleanup(bot)
    await install_operations_center(bot)

    global _INSTALLED
    if _INSTALLED:
        return

    command = bot.get_command("code")
    if command is not None:
        command.hidden = False
        logger.info("Commande +code conservée : raccourci IA spécialisé pour la génération de code.")
    else:
        logger.warning("Commande +code introuvable pendant le chargement du cog IA.")

    _INSTALLED = True
