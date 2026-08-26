"""Restaure les variantes slash des commandes directes hybrides désactivées historiquement.

Le projet avait mis de nombreuses ``hybrid_command`` en ``with_app_command=False`` pour
rester sous l'ancienne limite. Le budget central sait maintenant sélectionner au plus 100
racines : on peut donc reconstruire proprement l'Application Command fournie nativement
par discord.py, sans dupliquer la logique métier ni les paramètres.

Les commandes recréées depuis une commande + sont marquées explicitement. La surface
finale peut ainsi garder en priorité les vraies anciennes commandes / puis utiliser les
places restantes pour ces conversions + -> /.
"""
from __future__ import annotations

import logging

from discord.ext import commands
from discord.ext.commands.hybrid import HybridAppCommand

logger = logging.getLogger("bot.hybrid-slash-restore-v3")


def install(bot: commands.Bot) -> None:
    from .command_catalog_cleanup import NORMAL_DIRECT_COMMANDS

    restored = 0
    for direct_name in sorted(NORMAL_DIRECT_COMMANDS):
        if direct_name == "nickname":
            # /nick possède son alias slash court dédié avec ses contrôles de hiérarchie.
            continue

        command = bot.get_command(direct_name)
        if command is None or command.parent is not None:
            continue
        if not isinstance(command, commands.HybridCommand):
            continue

        slash_name = command.name.casefold()
        if bot.tree.get_command(slash_name) is not None:
            continue

        try:
            created_from_plus = command.app_command is None
            if created_from_plus:
                command.with_app_command = True
                command.app_command = HybridAppCommand(command)
                command._sentrix_slash_from_plus = True
            bot.tree.add_command(command.app_command, override=True)
            restored += 1
        except (TypeError, ValueError) as exc:
            # Certaines anciennes signatures ne sont pas représentables en slash. Elles
            # restent alors disponibles en + sans empêcher le reste du catalogue de boot.
            logger.debug("Slash non restaurable pour +%s: %s", direct_name, exc)

    if restored:
        logger.info("%s commande(s) hybride(s) directe(s) restaurée(s) en slash.", restored)
