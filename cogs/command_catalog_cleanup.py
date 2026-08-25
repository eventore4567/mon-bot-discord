"""Surface utilisateur canonique de SentriX.

SentriX conserve ses anciennes commandes préfixées pour la compatibilité, mais l'interface
normale ne doit plus demander de mémoriser un catalogue énorme. L'aide et Discord `/`
n'exposent donc qu'un petit ensemble de commandes essentielles. Les fonctions avancées
restent accessibles via leurs centres (`setup`, `security`, `ticket`, `giveaway`) ou via
les anciennes commandes `+` pour les utilisateurs qui les connaissent déjà.
"""
from __future__ import annotations

import logging
from discord.ext import commands

logger = logging.getLogger("bot.command-catalog-cleanup")
_INSTALLED = False

# Catalogue historique : conservé uniquement pour compatibilité des anciennes commandes +.
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

# Seulement quelques jeux immédiatement découvrables. Tous les autres restent disponibles
# avec le préfixe historique sans encombrer le sélecteur `/` de Discord.
POPULAR_GAME_COMMANDS = frozenset({
    "rps", "guess-number", "trivia", "blackjack", "slots",
})

# Surface normale : une trentaine de racines au lieu d'approcher la limite Discord de 100.
# Les actions rares de configuration/sécurité sont regroupées derrière /setup et /security.
EASY_SLASH_COMMANDS = frozenset({
    # Point d'entrée et informations
    "help", "ping", "avatar", "userinfo", "afk",
    # IA et création
    "sentrix", "image",
    # Membre / économie / progression
    "balance", "daily", "work", "pay", "inventory", "me", "level",
    # Support / événements
    "ticket", "giveaway",
    # Musique
    "play", "pause", "skip", "stop",
    # Administration guidée
    "setup", "security",
    # Modération quotidienne
    "ban", "unban", "kick", "mute", "unmute", "warn", "warnings", "clear",
    "lock", "unlock", "nickname",
}) | POPULAR_GAME_COMMANDS

# Nom historique utilisé par plusieurs audits/runtimes. Il désigne désormais volontairement
# la surface FACILE et non plus toutes les commandes que SentriX sait techniquement exécuter.
NORMAL_DIRECT_COMMANDS = EASY_SLASH_COMMANDS

# Commandes techniques : toujours utilisables en + avec leurs permissions, mais jamais
# présentées comme des points d'entrée normaux dans l'aide ou le catalogue slash.
ADMIN_DIRECT_COMMANDS = frozenset({
    "bl", "blinfo", "unbl", "editbl", "sync", "syncguild", "setstatus",
    "status-rotate", "footer", "theme", "set-bot", "bot-servers", "bot-leave",
    "wipe-server", "roleall", "massrole",
})

PURE_DUPLICATE_COMMANDS = frozenset({
    "rank", "buyrole", "ask", "chat", "embed-create", "latency", "levelroles",
})

SETUP_MERGED_COMMANDS = frozenset({
    "config-view", "config-reset", "create-logs", "logsetup", "logs-status",
    "designsetup", "welcome-config", "shopsetup", "aisetup", "setprefix", "setmodrole",
    "setwelcomechannel", "setwelcomemessage", "setgoodbyechannel",
    "setgoodbyemessage", "setlogchannel", "setticketlogchannel", "setwarnrole",
    "setannouncechannel", "setgiveawaychannel", "setsuggestchannel",
    "setlevelchannel", "setautorole", "createrole", "verify-setup", "verify-panel",
    "rolepanel", "rolepanel-refresh", "reactionrole-add", "reactionrole-remove",
    "reactionrole-list", "repconfig", "repadd", "repremove", "represet",
    "statsconfig", "addbonusinvites", "removebonusinvites", "invitebonushistory",
    "embedconfig", "set-nickname", "alias", "set-xp", "add-xp", "set-level-role",
    "remove-level-role", "reset-levels",
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
    "antiraid", "antinuke", "blacklist-add", "blacklist-users", "panic", "syncbl",
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
    "ai-translate", "chat-reset", "banque", "economyleaderboard", "leaderboard-money",
    "quarantine", "unquarantine", "resetnick", "giverole", "removerole",
}) | (GAME_COMMANDS - POPULAR_GAME_COMMANDS)

MERGED_COMMANDS = (
    SETUP_MERGED_COMMANDS
    | TICKET_MERGED_COMMANDS
    | GIVEAWAY_MERGED_COMMANDS
    | SECURITY_MERGED_COMMANDS
    | LOW_VALUE_HIDDEN_COMMANDS
)
INTENTIONALLY_REMOVED_COMMANDS = PURE_DUPLICATE_COMMANDS
CONFIRMED_DUPLICATE_COMMANDS = PURE_DUPLICATE_COMMANDS
RESTORED_COMMANDS = EASY_SLASH_COMMANDS
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


def slash_surface_names() -> frozenset[str]:
    """Noms racine réellement autorisés dans Discord `/`."""
    return frozenset("nick" if name == "nickname" else name for name in EASY_SLASH_COMMANDS)


def _install_short_command_names() -> None:
    try:
        from . import common_command_names
    except Exception:
        logger.exception("Impossible de charger le moteur de noms courts SentriX.")
        return
    common_command_names.PREFERRED_COMMAND_NAMES.update(SHORT_COMMAND_NAMES)
    common_command_names.PROTECTED_NAMES.update({"bl", "nick"})


def apply_surface(bot: commands.Bot) -> None:
    """L'aide montre seulement la surface facile ; les anciennes + restent exécutables."""
    for command in bot.commands:
        name = command.name.casefold()
        if name in EASY_SLASH_COMMANDS:
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
    """Installe la politique de découverte sans supprimer les fonctions historiques."""
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
        "Surface facile SentriX : %s racines principales (%s jeux visibles) ; "
        "les fonctions avancées restent disponibles via centres ou anciennes commandes +.",
        len(slash_surface_names()), len(POPULAR_GAME_COMMANDS),
    )
