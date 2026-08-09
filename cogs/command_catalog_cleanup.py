"""Politique canonique du catalogue de commandes SentriX.

Objectif : garder toutes les commandes qui apportent une vraie action, même lorsqu'un
panneau +setup permet aussi d'atteindre le même réglage, retirer uniquement les vrais
doublons et afficher des noms courts pour les commandes pénibles à taper.

Les anciens noms longs restent acceptés en compatibilité afin de ne casser aucun panneau,
script, ancien message d'aide ou habitude existante. +help présente en priorité le nom
court. Les commandes déjà courtes (ban, warn, antilink, antispam, antinuke, etc.) ne sont
pas supprimées.
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
    "ticketautoclose", "code", "me",
})

# Alias confirmés qui font exactement la même chose qu'une commande principale. Ils sont
# retirés du registre pour éviter un +help rempli de doublons inutiles.
# +me est volontairement conservé : c'est le raccourci personnel naturel pour afficher
# toutes ses statistiques (niveau, XP, messages, vocal, économie, réputation, etc.).
CONFIRMED_DUPLICATE_COMMANDS = frozenset({
    "leaderboard-money",  # economyleaderboard
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

# Rework demandé : les commandes utiles ne sont PAS supprimées juste parce que leur nom
# est long. Elles reçoivent un nom officiel court. L'ancien nom reste un alias silencieux
# pour compatibilité, tandis que +help affiche le raccourci ci-dessous.
SHORT_COMMAND_NAMES: dict[str, str] = {
    # Sécurité / AutoMod avancé.
    "antinuke-whitelist-add": "nukeadd",
    "antinuke-whitelist-list": "nukewl",
    "antinuke-whitelist-remove": "nukedel",
    "automod-exempt-role-add": "exemptadd",
    "automod-exempt-role-remove": "exemptdel",
    "automod-history": "amodlog",
    "automod-status": "amod",
    "security-check": "secscan",
    "security-level": "seclevel",
    "security-repair": "secfix",
    "permission-audit": "perms",
    "quarantine": "quar",
    "unquarantine": "unquar",
    "role-snapshot": "rolesave",
    "role-restore": "roleload",
    "server-backup": "backup",
    "server-restore": "restore",
    "whitelist-domain": "domainadd",
    "unwhitelist-domain": "domaindel",
    "lockdown-server": "lockdown",
    "unlock-server": "unlockdown",

    # Logs / configuration.
    "logs-status": "logstatus",
    "logsetup": "logconfig",
    "create-logs": "createlogs",
    "config-view": "config",
    "config-reset": "resetconfig",
    "designsetup": "design",
    "ticketsetup": "ticketcfg",
    "shopsetup": "shopcfg",
    "welcome-config": "welcome",

    # Anciennes commandes set... : gardées, mais beaucoup plus rapides à taper.
    "setwelcomechannel": "welcomech",
    "setwelcomemessage": "welcomemsg",
    "setgoodbyechannel": "goodbyech",
    "setgoodbyemessage": "goodbyemsg",
    "setlogchannel": "logch",
    "setticketlogchannel": "ticketlog",
    "setmodrole": "modrole",
    "setwarnrole": "warnrole",
    "setannouncechannel": "announcech",
    "setgiveawaychannel": "giveawaych",
    "setsuggestchannel": "suggestch",
    "setlevelchannel": "levelch",

    # Diagnostics / blacklist utilisateur.
    "diagnostic": "diag",
    "blacklist-user": "bluser",
    "unblacklist-user": "unbluser",
}

# Ces noms sont volontairement conservés tels quels. Ils sont courts, très reconnaissables
# ou avaient déjà été explicitement protégés dans SentriX.
KEEP_AS_IS = frozenset({
    "antiaccount", "antibot", "anticaps", "antiemoji", "antiinvite", "antilink",
    "antimention", "antinuke", "antiraid", "antiscam", "antispam", "aidiag",
    "bl", "blacklist-add", "blacklist-list", "blacklist-remove",
})


def _install_short_command_names() -> None:
    """Branche les nouveaux noms sur le moteur d'alias/help déjà utilisé par SentriX."""
    try:
        from . import common_command_names
    except Exception:
        logger.exception("Impossible de charger le moteur de noms courts SentriX.")
        return

    # Le moteur common_command_names ajoute l'alias au registre et mémorise le nom comme
    # nom préféré. Il est réappliqué après chaque extension, donc les cogs chargés plus
    # tard récupèrent eux aussi automatiquement leur raccourci.
    common_command_names.PREFERRED_COMMAND_NAMES.update(SHORT_COMMAND_NAMES)

    # Les commandes protégées conservent exactement leur nom historique.
    common_command_names.PROTECTED_NAMES.update({
        "bl", "blacklist-add", "blacklist-list", "blacklist-remove",
    })


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

    _install_short_command_names()

    _INSTALLED = True
    logger.info(
        "Catalogue SentriX rework : %s commandes utiles garanties, %s vrais doublons retirés, %s noms longs raccourcis.",
        len(RESTORED_COMMANDS),
        len(CONFIRMED_DUPLICATE_COMMANDS),
        len(SHORT_COMMAND_NAMES),
    )
