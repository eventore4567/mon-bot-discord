"""Compatibilité historique du loader IA et catalogue complet des commandes."""

from __future__ import annotations

import logging

from discord.ext import commands

from .command_catalog_cleanup import install as install_command_catalog_cleanup

logger = logging.getLogger("bot.remove-code-command")
_INSTALLED = False


def install(bot: commands.Bot) -> None:
    """Applique le catalogue canonique et conserve désormais +code comme commande utile."""
    # Cette fonction est appelée pendant le chargement du cog IA, donc avant le pruning
    # final de main.setup_hook(). Les commandes directes utiles sont ainsi restaurées avant
    # que le registre et +help soient construits définitivement.
    install_command_catalog_cleanup(bot)

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
