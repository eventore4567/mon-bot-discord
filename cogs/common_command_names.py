"""Ajoute des noms de commandes courts et familiers sans casser les noms internes."""
from __future__ import annotations

import logging
from discord.ext import commands

logger = logging.getLogger("bot.common-command-names")
_HELP_PATCHED = False

# Ne jamais renommer ces commandes, conformément au choix du propriétaire.
PROTECTED_NAMES = {"bl", "blacklist-add", "blacklist-list", "blacklist-remove"}

# Nom interne -> nom conseillé au membre. Les noms déjà universels (ban, kick, warn,
# mute, help, ping, play, shop...) restent tels quels.
PREFERRED_COMMAND_NAMES: dict[str, str] = {
    "membercount": "members",
    "emoji-list": "emojis",
    "reminder-list": "reminders",
    "reminder-cancel": "cancelreminder",
    "report-bug": "bugreport",
    "image-prompt": "prompt",
    "fact-check": "factcheck",
    "ai-translate": "aitranslate",
    "bot-status": "status",
    "server-growth": "growth",
    "command-stats": "cmdstats",
    "giveaway-list": "giveaways",
    "giveaway-create": "gcreate",
    "giveaway-end": "gend",
    "giveaway-reroll": "greroll",
    "giveaway-cancel": "gcancel",
    "giveaway-blacklist": "gblacklist",
    "giveaway-unblacklist": "gunblacklist",
    "event-join": "joinevent",
    "event-leave": "leaveevent",
    "event-list": "events",
    "event-create": "createevent",
    "event-cancel": "cancelevent",
    "tournament-join": "jointournament",
    "tournament-list": "tournaments",
    "tournament-create": "createtournament",
    "tournament-start": "starttournament",
    "invite-leaderboard": "invitetop",
    "invitebonushistory": "invitehistory",
    "addbonusinvites": "addinvites",
    "removebonusinvites": "removeinvites",
    "notifs-ping": "notify",
    "notifs-list": "notifications",
    "notifs-remove": "removenotif",
    "welcome-config": "welcome",
    "antiaccount": "antialt",
    "antinuke-whitelist-add": "nukewladd",
    "antinuke-whitelist-list": "nukewl",
    "antinuke-whitelist-remove": "nukewlremove",
    "automod-exempt-role-add": "exemptadd",
    "automod-exempt-role-remove": "exemptremove",
    "automod-history": "automodhistory",
    "automod-status": "automod",
    "permission-audit": "audit",
    "security-check": "security",
    "security-level": "securitylevel",
    "server-backup": "backup",
    "server-restore": "restore",
    "whitelist-domain": "whitelistdomain",
    "unwhitelist-domain": "unwhitelistdomain",
    "lockdown-server": "lockdown",
    "unlock-server": "unlockdown",
    "clearwarnings": "clearwarns",
    "modhistory": "history",
    "ticket-reopen": "reopen",
    "tickettranscript": "transcript",
    "sanctiondm": "sanctionmsg",
    "nowplaying": "np",
    "remove-from-queue": "remove",
    "clear-queue": "clearqueue",
    "playlist-save": "saveplaylist",
    "playlist-load": "loadplaylist",
    "guess-number": "guess",
    "math-quiz": "mathquiz",
    # `logs` est un ancien nom volontairement pruné dans main.py : ne pas le réutiliser.
    "logsetup": "logconfig",
    "logs-status": "logstatus",
    "create-logs": "createlogs",
    "config-view": "config",
    "config-reset": "resetconfig",
    "create-server": "setupserver",
    "delete-channel": "delchannel",
    "disablecommand": "disablecmd",
    "enablecommand": "enablecmd",
    "ignorechannel": "ignore",
    "unignorechannel": "unignore",
    "setwarnrole": "warnrole",
    "setwarnbanthreshold": "warnthreshold",
    "set-xp": "setxp",
    "add-xp": "addxp",
    "reset-levels": "resetlevels",
    "levelcheck": "checklevel",
    "levelrepair": "fixlevel",
    "designsetup": "design",
    "embedconfig": "embedsettings",
    "rolepanel": "roles",
    "rolepanel-refresh": "refreshroles",
    "reactionrole-add": "rradd",
    "reactionrole-remove": "rrremove",
    "reactionrole-list": "rrlist",
    "aisetup": "aiconfig",
    "diagnostic": "diagnose",
    "reset-economy": "reseteconomy",
    "status-rotate": "statusrotate",
    "bot-servers": "servers",
    "bot-leave": "leaveserver",
}


def preferred_name(command: commands.Command) -> str:
    extras = getattr(command, "extras", {}) or {}
    saved = extras.get("sentrix_preferred_name")
    if saved:
        return str(saved)
    qualified = str(getattr(command, "qualified_name", "") or "").strip()
    if not qualified:
        return str(getattr(command, "name", "") or "")
    root, *rest = qualified.split(" ")
    root = PREFERRED_COMMAND_NAMES.get(root, root)
    return " ".join([root, *rest]) if rest else root


def _register_alias(bot: commands.Bot, command: commands.Command, preferred: str) -> bool:
    if command.parent is not None:
        return False
    original = str(command.name)
    if original in PROTECTED_NAMES or preferred in PROTECTED_NAMES or original == preferred:
        return False

    existing = bot.all_commands.get(preferred)
    if existing is not None and existing is not command:
        logger.warning("Alias +%s ignoré : ce nom est déjà utilisé.", preferred)
        return False

    aliases = getattr(command, "aliases", None)
    if isinstance(aliases, list) and preferred not in aliases:
        aliases.append(preferred)
    bot.all_commands[preferred] = command
    command.extras["sentrix_preferred_name"] = preferred
    return True


def _patch_help_renderers() -> None:
    global _HELP_PATCHED
    if _HELP_PATCHED:
        return
    try:
        from . import utility
    except Exception:
        return

    original_format = utility.format_command_line
    original_search = utility.search_commands

    def format_command_line(command, prefix: str, slash_names: set) -> str:
        display = preferred_name(command)
        native = display == command.qualified_name
        marker = f"/ ou {prefix}" if native and command.qualified_name in slash_names else prefix
        usage = ""
        if isinstance(command, commands.HybridCommand) and command.clean_params:
            parts = [f"[{name}]" if param.required else f"({name})" for name, param in command.clean_params.items()]
            usage = " " + " ".join(parts)
        lock = "🔒 " if utility.is_staff_command(command) else ""
        return f"{lock}**`{marker}{display}{usage}`**\n╰ {command.description or 'Pas de description.'}"

    def search_commands(bot: commands.Bot, is_staff: bool, keyword: str):
        keyword = keyword.lower().strip()
        results = []
        seen = set()
        for cog_name, label in utility.CATEGORY_LABELS.items():
            cog = bot.get_cog(cog_name)
            if not cog or not utility.category_visible(cog_name, cog, is_staff):
                continue
            for command in utility.visible_commands(cog, is_staff):
                aliases = " ".join(getattr(command, "aliases", []) or [])
                haystack = f"{command.qualified_name} {preferred_name(command)} {aliases} {command.description or ''}".lower()
                if keyword in haystack and id(command) not in seen:
                    seen.add(id(command))
                    results.append((label, command))
        return results

    utility.format_command_line = format_command_line
    utility.search_commands = search_commands
    utility._sentrix_original_format_command_line = original_format
    utility._sentrix_original_search_commands = original_search

    try:
        from . import help_complete

        def command_usage(command, prefix: str) -> str:
            parts = [f"{prefix}{preferred_name(command)}"]
            for name, parameter in getattr(command, "clean_params", {}).items():
                if name in {"ctx", "context", "interaction", "self"}:
                    continue
                parts.append(f"<{name}>" if getattr(parameter, "required", False) else f"[{name}]")
            return " ".join(parts)

        help_complete._command_usage = command_usage
    except Exception:
        pass

    _HELP_PATCHED = True
    logger.info("+help affiche désormais les noms de commandes familiers.")


def install(bot: commands.Bot) -> None:
    added = 0
    for command in list(bot.walk_commands()):
        if command.parent is not None:
            continue
        preferred = PREFERRED_COMMAND_NAMES.get(str(command.name))
        if preferred and _register_alias(bot, command, preferred):
            added += 1
    _patch_help_renderers()
    if added:
        logger.info("%s alias de commandes familiers ajoutés.", added)
