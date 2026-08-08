"""Supprime complètement l'ancienne commande +code de SentriX."""

from __future__ import annotations

import logging

from discord.ext import commands

from .command_catalog_cleanup import install as install_command_catalog_cleanup

logger = logging.getLogger("bot.remove-code-command")
_INSTALLED = False


def install(bot: commands.Bot) -> None:
    """Applique le catalogue canonique puis retire l'ancienne commande +code."""
    # Cette fonction est appelée pendant le chargement du cog IA, donc avant le pruning
    # final de main.setup_hook(). Les commandes directes utiles sont ainsi restaurées avant
    # que le registre et +help soient construits définitivement.
    install_command_catalog_cleanup(bot)

    global _INSTALLED
    if _INSTALLED:
        return

    command = bot.get_command("code")
    if command is not None:
        # Le panneau d'aide parcourt aussi les commandes conservées dans le Cog.
        # hidden=True garantit donc qu'elle n'apparaît plus, même après désenregistrement.
        command.hidden = True
        removed = bot.remove_command("code")
        if removed is not None:
            logger.info("Commande +code supprimée et retirée de l'aide.")
        else:
            logger.warning("Commande +code trouvée mais impossible à désenregistrer.")
    else:
        logger.info("Commande +code déjà absente.")

    _INSTALLED = True
