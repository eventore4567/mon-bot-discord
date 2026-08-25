"""Catalogue utilisateur canonique de SentriX.

Deux objectifs différents sont volontairement séparés :
- Discord `/` conserve presque toute l'ancienne surface utile, jusqu'au budget de 100 racines ;
- `+help` reste facile à parcourir et à rechercher sans afficher chaque ancien réglage fusionné.

Les anciennes commandes `+` restent exécutables pour la compatibilité. Seuls les vrais doublons
et les commandes remplacées par un centre canonique sont masqués de l'aide.
"""
from __future__ import annotations

import logging
from discord.ext import commands

logger = logging.getLogger("bot.command-catalog-cleanup")
_INSTALLED = False

GAME_COMMANDS = frozenset({
    "rps", "guess-number", "trivia", "tictactoe", "hangman", "math-quiz",
    "blackjack", "slots", "coinflip", "dice", "luckyroll", "highlow", "memory",
    "reaction", "scramble", "wordgame", "emojiquiz", "colorquiz", "fasttype",
    "duel", "connect4", "numberduel", "reactionduel", "quizduel", "triviastart",
    "wordrace", "reactionevent", "guessrace", "mathrace", "lastmessage",
    "emoji-race", "adventure", "dungeon", "mining", "fishing", "treasure",
    "hunt", "explore", "gamehistory", "gameprofile", "gamestats", "gametop",
    "dailygames",
})

# Surface slash proche de l'ancienne expérience SentriX : on ne réduit PAS Discord à
# quelques commandes. On retire seulement les réglages/doublons qui ont désormais un
# meilleur point d'entrée, puis on utilise les places libérées pour des commandes + utiles.
SLASH_COMMANDS = frozenset({
    # Aide / informations / utilitaires
    "help", "setup", "ping", "avatar", "userinfo", "afk", "info", "membercount",
    "poll", "remind", "translate", "weather",
    # Modération quotidienne
    "ban", "unban", "kick", "mute", "unmute", "warn", "warnings", "clear",
    "lock", "unlock", "quarantine", "unquarantine", "nickname", "resetnick",
    "giverole", "removerole",
    # Centre sécurité : les anciennes racines anti-* restent disponibles en +
    "security",
    # IA
    "sentrix", "image", "ai-translate", "chat-reset",
    # Économie / progression
    "balance", "daily", "work", "pay", "inventory", "banque", "economyleaderboard",
    "me", "level", "set-xp", "add-xp", "set-level-role", "remove-level-role",
    "reset-levels", "profile", "shop", "deposit", "gamble",
    # Centres support / événements
    "ticket", "giveaway",
    # Musique
    "play", "pause", "skip", "stop",
}) | GAME_COMMANDS

# Alias historique utilisé par les anciens audits/runtimes.
NORMAL_DIRECT_COMMANDS = SLASH_COMMANDS
EASY_SLASH_COMMANDS = SLASH_COMMANDS
POPULAR_GAME_COMMANDS = GAME_COMMANDS

ADMIN_DIRECT_COMMANDS = frozenset({
    "bl", "blinfo", "unbl", "editbl", "sync", "syncguild", "setstatus",
    "status-rotate", "footer", "theme", "set-bot", "bot-servers", "bot-leave",
    "wipe-server", "roleall", "massrole",
})

PURE_DUPLICATE_COMMANDS = frozenset({
    "rank", "buyrole", "ask", "chat", "embed-create", "latency", "levelroles",
    "leaderboard-money",
})

# Ces commandes existent toujours en + pour les anciens panneaux/scripts, mais l'aide ne
# les présente plus individuellement : elles sont mieux trouvées depuis leur centre.
SETUP_MERGED_COMMANDS = frozenset({
    "config-view", "config-reset", "create-logs", "logsetup", "logs-status",
    "designsetup", "welcome-config", "shopsetup", "aisetup", "setprefix", "setmodrole",
    "setwelcomechannel", "setwelcomemessage", "setgoodbyechannel", "setgoodbyemessage",
    "setlogchannel", "setticketlogchannel", "setwarnrole", "setannouncechannel",
    "setgiveawaychannel", "setsuggestchannel", "setlevelchannel", "setautorole",
    "createrole", "verify-setup", "verify-panel", "rolepanel", "rolepanel-refresh",
    "reactionrole-add", "reactionrole-remove", "reactionrole-list", "repconfig",
    "repadd", "repremove", "represet", "statsconfig", "addbonusinvites",
    "removebonusinvites", "invitebonushistory", "embedconfig", "set-nickname", "alias",
})

TICKET_MERGED_COMMANDS = frozenset({
    "ticketsetup", "ticketpanel", "ticketpanel-toggle", "tickettype", "ticketform",
    "ticketconfig", "ticketlogs", "ticketlimit", "ticketautoclose",
    "ticket-reopen", "tickettranscript", "ticketstats",
})

GIVEAWAY_MERGED_COMMANDS = frozenset({
    "giveaway-create", "giveaway-end", "giveaway-cancel", "giveaway-reroll",
    "giveaway-blacklist", "giveaway-unblacklist", "giveaway-list",
})

SECURITY_MERGED_COMMANDS = frozenset({
    "antispam", "antilink", "antiinvite", "antimention", "anticaps", "antiemoji",
    "antiraid", "antibot", "antiaccount", "antiscam", "antinuke", "panic", "syncbl",
    "antinuke-whitelist-add", "antinuke-whitelist-list", "antinuke-whitelist-remove",
    "automod-exempt-role-add", "automod-exempt-role-remove", "automod-history",
    "automod-status", "security-check", "security-level", "security-repair",
    "whitelist-domain", "unwhitelist-domain", "blacklist-add", "blacklist-list",
    "blacklist-remove", "blacklist-user", "blacklist-users", "unblacklist-user",
    "permission-audit", "server-backup", "server-restore", "unsyncbl",
    "role-snapshot", "role-restore", "lockdown-server", "unlock-server",
})

MERGED_COMMANDS = (
    SETUP_MERGED_COMMANDS | TICKET_MERGED_COMMANDS | GIVEAWAY_MERGED_COMMANDS |
    SECURITY_MERGED_COMMANDS
)
INTENTIONALLY_REMOVED_COMMANDS = PURE_DUPLICATE_COMMANDS
CONFIRMED_DUPLICATE_COMMANDS = PURE_DUPLICATE_COMMANDS
RESTORED_COMMANDS = SLASH_COMMANDS
LOW_VALUE_REMOVED_COMMANDS = frozenset()
LOW_VALUE_HIDDEN_COMMANDS = frozenset()

MERGED_COMMAND_TARGETS: dict[str, str] = {
    **{name: "setup" for name in SETUP_MERGED_COMMANDS},
    **{name: "ticket" for name in TICKET_MERGED_COMMANDS},
    **{name: "giveaway" for name in GIVEAWAY_MERGED_COMMANDS},
    **{name: "security" for name in SECURITY_MERGED_COMMANDS},
}

SHORT_COMMAND_NAMES: dict[str, str] = {
    "permission-audit": "perms", "quarantine": "quar", "unquarantine": "unquar",
    "role-snapshot": "rolesave", "role-restore": "roleload", "server-backup": "backup",
    "server-restore": "restore", "lockdown-server": "lockdown",
    "unlock-server": "unlockdown",
}
KEEP_AS_IS = frozenset({"bl", "nick"})

# Ce qui doit disparaître de +help, mais PAS de l'exécution préfixée historique.
HELP_HIDDEN_COMMANDS = PURE_DUPLICATE_COMMANDS | MERGED_COMMANDS


def slash_surface_names() -> frozenset[str]:
    """Noms racine autorisés dans Discord `/` (nickname est exposé sous `/nick`)."""
    return frozenset("nick" if name == "nickname" else name for name in SLASH_COMMANDS)


def _install_short_command_names() -> None:
    try:
        from . import common_command_names
    except Exception:
        logger.exception("Impossible de charger le moteur de noms courts SentriX.")
        return
    common_command_names.PREFERRED_COMMAND_NAMES.update(SHORT_COMMAND_NAMES)
    common_command_names.PROTECTED_NAMES.update({"bl", "nick"})


def apply_surface(bot: commands.Bot) -> None:
    """Rend les commandes + faciles à découvrir sans réafficher les anciens doublons."""
    for command in bot.commands:
        name = command.name.casefold()
        command.hidden = name in HELP_HIDDEN_COMMANDS

    help_command = bot.get_command("help")
    if help_command is not None:
        help_command.hidden = False
        checks = getattr(help_command, "checks", None)
        if isinstance(checks, list):
            checks.clear()
        app = getattr(help_command, "app_command", None)
        app_checks = getattr(app, "checks", None)
        if isinstance(app_checks, list):
            app_checks.clear()


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    import main

    if not _INSTALLED:
        main.COMMANDS_REPLACED_BY_SETUP = frozenset()
        main.EXACT_DUPLICATE_COMMANDS = PURE_DUPLICATE_COMMANDS
        main.PRUNED_COMMANDS = PURE_DUPLICATE_COMMANDS
        main.PUBLIC_COMMANDS = main.PUBLIC_COMMANDS | {"help", "ticket", "giveaway"}
        main.KNOWN_PERMISSION_COMMANDS = (
            main.PUBLIC_COMMANDS | main.OWNER_ONLY_COMMANDS | main.CUSTOM_PERMISSION_COMMANDS |
            frozenset(main.DISCORD_PERMISSION_COMMANDS) |
            frozenset().union(*main.CATEGORY_COMMANDS.values()) |
            {"giveaway", "ticket", "security", "panic"}
        )
        _install_short_command_names()
        _INSTALLED = True

    apply_surface(bot)
    logger.info(
        "Catalogue SentriX : %s racines slash utiles ; anciennes commandes + recherchables, "
        "doublons/anciens réglages fusionnés masqués de l'aide.",
        len(slash_surface_names()),
    )
