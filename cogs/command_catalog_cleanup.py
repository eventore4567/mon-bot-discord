"""Surface canonique des commandes SentriX.

Les fonctionnalités historiques restent chargées pour compatibilité, mais l'aide et les
commandes slash n'exposent que la surface directe décidée. Les anciens réglages fusionnés
restent utilisables en préfixe + par les habitués, tout en étant masqués de +help.
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

NORMAL_DIRECT_COMMANDS = frozenset({
    "help", "setup", "ping", "avatar", "userinfo", "afk", "setprefix", "setmodrole",
    "ban", "unban", "kick", "mute", "unmute", "warn", "warnings", "clear",
    "lock", "unlock", "quarantine", "unquarantine", "nickname", "resetnick",
    "giverole", "removerole",
    "security", "antiraid", "antinuke", "blacklist-add", "blacklist-users",
    "panic", "syncbl",
    "sentrix", "image", "ai-translate", "chat-reset",
    "balance", "daily", "work", "pay", "inventory", "banque",
    "economyleaderboard", "leaderboard-money",
    "me", "level", "set-xp", "add-xp", "set-level-role", "remove-level-role",
    "reset-levels",
    "ticket", "giveaway", "giveaway-reroll",
    "play", "pause", "skip", "stop",
}) | GAME_COMMANDS

ADMIN_DIRECT_COMMANDS = frozenset({
    "bl", "blinfo", "unbl", "editbl", "sync", "syncguild", "setstatus",
    "status-rotate", "footer", "theme", "set-bot", "bot-servers", "bot-leave",
    "wipe-server", "roleall", "massrole",
})

# Nouveau système transverse : visible dans +help sans le classer dans les anciennes
# commandes admin « + uniquement ». Le budget slash décide séparément quelles racines
# peuvent être publiées sans dépasser la limite Discord de 100 commandes globales.
PROOF_VISIBLE_COMMANDS = frozenset({
    "proof", "proofstatus", "proofsetup", "proofexample", "proofexample-remove",
    "proofexamples", "proofpanel", "proofreset",
})

PURE_DUPLICATE_COMMANDS = frozenset({
    "rank", "buyrole", "ask", "chat", "embed-create", "latency", "levelroles",
})

SETUP_MERGED_COMMANDS = frozenset({
    "config-view", "config-reset", "create-logs", "logsetup", "logs-status",
    "designsetup", "welcome-config", "shopsetup", "aisetup",
    "setwelcomechannel", "setwelcomemessage", "setgoodbyechannel",
    "setgoodbyemessage", "setlogchannel", "setticketlogchannel", "setwarnrole",
    "setannouncechannel", "setgiveawaychannel", "setsuggestchannel",
    "setlevelchannel", "setautorole", "createrole", "verify-setup", "verify-panel",
    "rolepanel", "rolepanel-refresh", "reactionrole-add", "reactionrole-remove",
    "reactionrole-list", "repconfig", "repadd", "repremove", "represet",
    "statsconfig", "addbonusinvites", "removebonusinvites", "invitebonushistory",
    "embedconfig", "set-nickname", "alias",
})

TICKET_MERGED_COMMANDS = frozenset({
    "ticketsetup", "ticketpanel", "ticketpanel-toggle", "tickettype", "ticketform",
    "ticketconfig", "ticketlogs", "ticketlimit", "ticketautoclose",
    "ticket-reopen", "tickettranscript", "ticketstats",
})

GIVEAWAY_MERGED_COMMANDS = frozenset({
    "giveaway-create", "giveaway-end", "giveaway-cancel",
    "giveaway-blacklist", "giveaway-unblacklist", "giveaway-list",
})

SECURITY_MERGED_COMMANDS = frozenset({
    "antinuke-whitelist-add", "antinuke-whitelist-list",
    "antinuke-whitelist-remove", "automod-exempt-role-add",
    "automod-exempt-role-remove", "automod-history", "automod-status",
    "security-check", "security-level", "security-repair",
    "whitelist-domain", "unwhitelist-domain", "blacklist-list",
    "blacklist-remove", "blacklist-user", "unblacklist-user",
    "permission-audit", "server-backup", "server-restore", "unsyncbl",
    "role-snapshot", "role-restore", "lockdown-server", "unlock-server",
})

LOW_VALUE_HIDDEN_COMMANDS = frozenset({
    "aidiag", "diagnostic", "bot-status", "command-stats", "levelcheck",
    "levelrepair", "weekly", "rewrite", "shop", "resume", "queue", "profile",
})

MERGED_COMMANDS = (
    SETUP_MERGED_COMMANDS
    | TICKET_MERGED_COMMANDS
    | GIVEAWAY_MERGED_COMMANDS
    | SECURITY_MERGED_COMMANDS
    | LOW_VALUE_HIDDEN_COMMANDS
)
INTENTIONALLY_REMOVED_COMMANDS = PURE_DUPLICATE_COMMANDS
CONFIRMED_DUPLICATE_COMMANDS = PURE_DUPLICATE_COMMANDS
RESTORED_COMMANDS = NORMAL_DIRECT_COMMANDS | PROOF_VISIBLE_COMMANDS
LOW_VALUE_REMOVED_COMMANDS = LOW_VALUE_HIDDEN_COMMANDS

MERGED_COMMAND_TARGETS: dict[str, str] = {
    **{name: "setup" for name in SETUP_MERGED_COMMANDS},
    **{name: "ticket" for name in TICKET_MERGED_COMMANDS},
    **{name: "giveaway" for name in GIVEAWAY_MERGED_COMMANDS},
    **{name: "security" for name in SECURITY_MERGED_COMMANDS},
}

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
KEEP_AS_IS = frozenset({
    "antiaccount", "antibot", "anticaps", "antiemoji", "antiinvite", "antilink",
    "antimention", "antinuke", "antiraid", "antiscam", "antispam", "bl",
})


def _install_short_command_names() -> None:
    try:
        from . import common_command_names
    except Exception:
        logger.exception("Impossible de charger le moteur de noms courts SentriX.")
        return
    common_command_names.PREFERRED_COMMAND_NAMES.update(SHORT_COMMAND_NAMES)
    common_command_names.PROTECTED_NAMES.update({"bl", "nick"})


def apply_surface(bot: commands.Bot) -> None:
    """Rend visibles uniquement les commandes directes, sans casser les anciennes +."""
    direct = NORMAL_DIRECT_COMMANDS | ADMIN_DIRECT_COMMANDS | PROOF_VISIBLE_COMMANDS
    for command in bot.commands:
        name = command.name.casefold()
        if name in direct:
            command.hidden = False
        elif name in PURE_DUPLICATE_COMMANDS:
            continue
        else:
            command.hidden = True

    help_command = bot.get_command("help")
    if help_command is not None:
        help_command.hidden = False
        command_checks = getattr(help_command, "checks", None)
        if isinstance(command_checks, list):
            command_checks.clear()
        app = getattr(help_command, "app_command", None)
        app_checks = getattr(app, "checks", None)
        if isinstance(app_checks, list):
            app_checks.clear()


def install(bot: commands.Bot) -> None:
    """Installe la politique puis la réapplique après chaque chargement de cog."""
    global _INSTALLED
    import main

    if not _INSTALLED:
        main.COMMANDS_REPLACED_BY_SETUP = frozenset()
        main.EXACT_DUPLICATE_COMMANDS = PURE_DUPLICATE_COMMANDS
        main.PRUNED_COMMANDS = PURE_DUPLICATE_COMMANDS
        main.PUBLIC_COMMANDS = main.PUBLIC_COMMANDS | {"help", "ticket", "giveaway"}
        main.KNOWN_PERMISSION_COMMANDS = (
            main.PUBLIC_COMMANDS
            | main.OWNER_ONLY_COMMANDS
            | main.CUSTOM_PERMISSION_COMMANDS
            | frozenset(main.DISCORD_PERMISSION_COMMANDS)
            | frozenset().union(*main.CATEGORY_COMMANDS.values())
            | {"giveaway", "ticket", "security", "panic"}
        )
        _install_short_command_names()
        _INSTALLED = True

    apply_surface(bot)
    logger.info(
        "Surface SentriX : %s commandes directes normales, %s admin, %s proof, %s jeux; "
        "anciennes commandes fusionnées conservées en + mais masquées.",
        len(NORMAL_DIRECT_COMMANDS), len(ADMIN_DIRECT_COMMANDS), len(PROOF_VISIBLE_COMMANDS), len(GAME_COMMANDS),
    )