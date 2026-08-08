"""Politique canonique du catalogue de commandes SentriX.

Objectif : garder toutes les commandes qui apportent une vraie action, même lorsqu'un
panneau +setup permet aussi d'atteindre le même réglage, et retirer uniquement les alias
qui exécutent exactement la même action qu'une commande principale déjà conservée.
"""
from __future__ import annotations

import logging

from discord.ext import commands

logger = logging.getLogger("bot.command-catalog-cleanup")
_INSTALLED = False

# Commandes auparavant retirées uniquement parce qu'elles étaient accessibles depuis un
# panneau +setup, plus +code qui reste utile comme raccourci IA spécialisé. Elles doivent
# toutes exister dans le registre et donc apparaître automatiquement dans +help.
RESTORED_COMMANDS = frozenset({
    "setprefix", "setmodrole", "setlogchannel", "create-logs", "logs",
    "setwelcomechannel", "setgoodbyechannel", "setwelcomemessage",
    "setgoodbyemessage", "setticketlogchannel", "setautorole", "createrole",
    "setlevelchannel", "setsuggestchannel", "setannouncechannel",
    "setgiveawaychannel", "verify-setup", "set-level-role",
    "remove-level-role", "level-roles", "ticketpanel", "ticketpanel-toggle",
    "tickettype", "ticketform", "ticketconfig", "ticketlogs", "ticketlimit",
    "ticketautoclose", "code",
})

# Alias confirmés qui font exactement la même chose qu'une commande principale. Ils sont
# retirés du registre pour éviter un +help rempli de doublons inutiles.
CONFIRMED_DUPLICATE_COMMANDS = frozenset({
    "leaderboard-money",  # economyleaderboard
    "me",                 # stats
    "rank",               # level
    "buyrole",            # buy
    "ask",                # ancienne entrée IA, remplacée par ai
    "chat",               # même pipeline que ai
    "chat-reset",         # ancien reset, remplacé proprement par +ai reset
    "embed-create",       # embed create
    "latency",            # ping
    "levelroles",         # statsconfig ouvert directement sur la page niveaux
})

INTENTIONALLY_REMOVED_COMMANDS = CONFIRMED_DUPLICATE_COMMANDS


def install(bot: commands.Bot) -> None:
    """Applique la politique avant le nettoyage final exécuté dans main.setup_hook()."""
    del bot
    global _INSTALLED
    if _INSTALLED:
        return

    # main est déjà chargé lorsque le premier cog passe par le loader SentriX. Modifier
    # ces ensembles ici permet de conserver le mécanisme de pruning existant sans toucher
    # aux implémentations internes utilisées par les anciens panneaux persistants.
    import main

    main.COMMANDS_REPLACED_BY_SETUP = frozenset()
    main.EXACT_DUPLICATE_COMMANDS = CONFIRMED_DUPLICATE_COMMANDS
    main.PRUNED_COMMANDS = CONFIRMED_DUPLICATE_COMMANDS

    _INSTALLED = True
    logger.info(
        "Catalogue complet activé : %s commandes utiles garanties, %s doublons retirés.",
        len(RESTORED_COMMANDS),
        len(CONFIRMED_DUPLICATE_COMMANDS),
    )
