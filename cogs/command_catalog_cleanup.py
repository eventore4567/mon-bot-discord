"""Politique canonique du catalogue de commandes SentriX.

Objectif : garder les commandes qui apportent une vraie action, fusionner les anciens
réglages dans les centres +security / +setup et retirer les entrées réellement inutiles.

Le code interne des commandes fusionnées reste chargé : les panneaux, services et données
historiques continuent donc de fonctionner. Seule leur ancienne entrée publique disparaît
du registre Discord, de +help et des commandes slash.
"""
from __future__ import annotations

import logging

from discord.ext import commands

logger = logging.getLogger("bot.command-catalog-cleanup")
_INSTALLED = False

# Commandes uniques qui avaient autrefois été masquées uniquement parce qu'un panneau
# proposait aussi la fonction. Elles restent publiques : elles apportent encore une action
# utile qu'on ne veut pas perdre pendant le nettoyage du catalogue.
RESTORED_COMMANDS = frozenset({
    "logs", "createrole", "verify-setup", "set-level-role",
    "remove-level-role", "level-roles", "ticketpanel", "ticketpanel-toggle",
    "tickettype", "ticketform", "ticketconfig", "ticketlogs", "ticketlimit",
    "ticketautoclose", "code", "me",
})

# 9 vrais doublons : aucune fonction n'est perdue, une commande canonique existe déjà.
PURE_DUPLICATE_COMMANDS = frozenset({
    "leaderboard-money",  # economyleaderboard
    "rank",               # level
    "buyrole",            # buy
    "ask",                # ai
    "chat",               # ai
    "chat-reset",         # ai reset
    "embed-create",       # embed create
    "latency",            # ping
    "levelroles",         # statsconfig / level-roles
})

# Anciens réglages désormais regroupés dans le centre +setup ou le dashboard.
SETUP_MERGED_COMMANDS = frozenset({
    "config-view", "config-reset", "create-logs", "logsetup", "logs-status",
    "designsetup", "welcome-config", "shopsetup", "ticketsetup", "aisetup",
    "setwelcomechannel", "setwelcomemessage", "setgoodbyechannel",
    "setgoodbyemessage", "setlogchannel", "setticketlogchannel", "setmodrole",
    "setwarnrole", "setannouncechannel", "setgiveawaychannel",
    "setsuggestchannel", "setlevelchannel", "setautorole", "setprefix",
})

# Anciennes entrées de sécurité dont la fonction est maintenant implémentée directement
# dans +security. On ne retire PAS quarantine/backup/role-restore/etc. ici : les wrappers
# avancés +security réutilisent encore leurs implémentations internes.
SECURITY_MERGED_COMMANDS = frozenset({
    "antinuke-whitelist-add", "antinuke-whitelist-list",
    "antinuke-whitelist-remove", "automod-exempt-role-add",
    "automod-exempt-role-remove", "automod-history", "automod-status",
    "security-check", "security-level", "security-repair",
    "whitelist-domain", "unwhitelist-domain",
})

# Ancienne blacklist serveur remplacée par +security blacklist ...
BLACKLIST_MERGED_COMMANDS = frozenset({
    "blacklist-add", "blacklist-list", "blacklist-remove",
    "blacklist-user", "blacklist-users", "unblacklist-user",
})

# Commandes réellement retirées car trop secondaires/techniques pour le catalogue public.
# Les fonctions principales équivalentes restent accessibles via +health ou le dashboard
# quand c'est pertinent ; les outils propriétaire très niche disparaissent volontairement.
LOW_VALUE_REMOVED_COMMANDS = frozenset({
    "aidiag", "diagnostic", "bot-status", "command-stats", "bot-servers",
    "bot-leave", "levelcheck", "levelrepair", "status-rotate",
})

MERGED_COMMANDS = (
    SETUP_MERGED_COMMANDS
    | SECURITY_MERGED_COMMANDS
    | BLACKLIST_MERGED_COMMANDS
)

INTENTIONALLY_REMOVED_COMMANDS = (
    PURE_DUPLICATE_COMMANDS
    | MERGED_COMMANDS
    | LOW_VALUE_REMOVED_COMMANDS
)

# Compatibilité avec les audits / couches plus anciennes qui importaient ce nom.
CONFIRMED_DUPLICATE_COMMANDS = PURE_DUPLICATE_COMMANDS

# Documentation machine-lisible des destinations des commandes fusionnées. La CI vérifie
# que la racine cible existe réellement après le nettoyage.
MERGED_COMMAND_TARGETS: dict[str, str] = {
    # Setup / dashboard.
    **{name: "setup" for name in SETUP_MERGED_COMMANDS},
    # Sécurité.
    "antinuke-whitelist-add": "security whitelist user-add",
    "antinuke-whitelist-list": "security whitelist users",
    "antinuke-whitelist-remove": "security whitelist user-remove",
    "automod-exempt-role-add": "security whitelist role-add",
    "automod-exempt-role-remove": "security whitelist role-remove",
    "automod-history": "security history",
    "automod-status": "security status",
    "security-check": "security scan",
    "security-level": "security level",
    "security-repair": "security repair",
    "whitelist-domain": "security whitelist domain-add",
    "unwhitelist-domain": "security whitelist domain-remove",
    # Blacklist serveur.
    "blacklist-add": "security blacklist word-add",
    "blacklist-list": "security blacklist words",
    "blacklist-remove": "security blacklist word-remove",
    "blacklist-user": "security blacklist user-add",
    "blacklist-users": "security blacklist users",
    "unblacklist-user": "security blacklist user-remove",
}

# Les commandes longues encore nécessaires reçoivent un raccourci officiel. Elles ne sont
# pas supprimées car +security les utilise encore comme moteur interne pour certaines
# actions avancées.
SHORT_COMMAND_NAMES: dict[str, str] = {
    "permission-audit": "perms",
    "quarantine": "quar",
    "unquarantine": "unquar",
    "role-snapshot": "rolesave",
    "role-restore": "roleload",
    "server-backup": "backup",
    "server-restore": "restore",
    "lockdown-server": "lockdown",
    "unlock-server": "unlockdown",
}

# Noms courts et importants à ne jamais renommer/supprimer par une future couche d'alias.
KEEP_AS_IS = frozenset({
    "antiaccount", "antibot", "anticaps", "antiemoji", "antiinvite", "antilink",
    "antimention", "antinuke", "antiraid", "antiscam", "antispam", "bl",
})


def _install_short_command_names() -> None:
    """Branche les raccourcis conservés sur le moteur d'alias/help SentriX."""
    try:
        from . import common_command_names
    except Exception:
        logger.exception("Impossible de charger le moteur de noms courts SentriX.")
        return

    common_command_names.PREFERRED_COMMAND_NAMES.update(SHORT_COMMAND_NAMES)
    common_command_names.PROTECTED_NAMES.update({"bl"})


def install(bot: commands.Bot) -> None:
    """Applique le catalogue slim avant le pruning final de main.setup_hook()."""
    del bot
    global _INSTALLED
    if _INSTALLED:
        return

    import main

    # Le moteur de pruning de main retire les commandes du préfixe, de +help et du tree
    # slash après le chargement de tous les cogs. Les implémentations Python restent dans
    # leurs cogs afin que les panneaux/services internes ne soient pas détruits.
    main.COMMANDS_REPLACED_BY_SETUP = MERGED_COMMANDS
    main.EXACT_DUPLICATE_COMMANDS = PURE_DUPLICATE_COMMANDS | LOW_VALUE_REMOVED_COMMANDS
    main.PRUNED_COMMANDS = INTENTIONALLY_REMOVED_COMMANDS

    _install_short_command_names()

    _INSTALLED = True
    logger.info(
        "Catalogue SentriX slim : %s racines retirées (%s doublons, %s fusionnées, %s faibles), %s commandes uniques garanties.",
        len(INTENTIONALLY_REMOVED_COMMANDS),
        len(PURE_DUPLICATE_COMMANDS),
        len(MERGED_COMMANDS),
        len(LOW_VALUE_REMOVED_COMMANDS),
        len(RESTORED_COMMANDS),
    )
