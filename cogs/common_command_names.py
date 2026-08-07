"""Noms de commandes courts et familiers pour SentriX.

Les commandes historiques restent la source interne afin de ne pas casser les checks,
les permissions, les appels entre cogs ni les commandes slash déjà publiées. Pour les
commandes texte, on ajoute un nom préféré (alias) plus proche de ce que les utilisateurs
retrouvent sur les bots Discord connus, puis +help affiche ce nom en priorité.

Exemple : +membercount continue de fonctionner, mais +members devient le nom conseillé.
"""

from __future__ import annotations

import logging

from discord.ext import commands

logger = logging.getLogger("bot.common-command-names")
_HELP_PATCHED = False

# Demande explicite : ne pas toucher à +bl ni aux commandes de blacklist de mots.
PROTECTED_NAMES = {
    "bl",
    "blacklist-add",
    "blacklist-list",
    "blacklist-remove",
}

# ancien nom interne -> nom conseillé au membre.
# Les commandes déjà standards (ban, kick, warn, mute, play, shop, help, ping...) ne sont
# volontairement pas listées : les renommer rendrait le bot moins familier, pas plus.
PREFERRED_COMMAND_NAMES: dict[str, str] = {
    # Informations / utilitaires
    "membercount": "members",
    "emoji-list": "emojis",
    "reminder-list": "reminders",
    "reminder-cancel": "cancelreminder",
    "report-bug": "bugreport",
    "image-prompt": "prompt",
    "fact-check": "factcheck",
    "ai-translate": "aitranslate",

    # Statistiques / bot
    "bot-status": "status",
    "server-growth": "growth",
    "command-stats": "cmdstats",

    # Giveaways / événements
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

    # Invitations / notifications
    "invite-leaderboard": "invitetop",
    "invitebonushistory": "invitehistory",
    "addbonusinvites": "addinvites",
    "removebonusinvites": "removeinvites",
    "notifs-ping": "notify",
    "notifs-list": "notifications",
    "notifs-remove": "removenotif",
    "welcome-config": "welcome",

    # Sécurité (les blacklists de mots restent inchangées)
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

    # Sanctions / modération
    "clearwarnings": "clearwarns",
    "modhistory": "history",
    "ticket-reopen": "reopen",
    "tickettranscript": "transcript",
    "sanctiondm": "sanctionmsg",

    # Musique
    "nowplaying": "np",
    "remove-from-queue": "remove",
    "clear-queue": "clearqueue",
    "playlist-save": "saveplaylist",
    "playlist-load": "loadplaylist",

    # Jeux
    "guess-number": "guess",
    "math-quiz": "mathquiz",

    # Configuration / serveur
    "logsetup": "logs",
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

    # Propriétaire du bot — +bl reste volontairement inchangé
    "status-rotate": "statusrotate",
    "bot-servers": "servers",
    "bot-leave": "leaveserver",
}


def preferred_name(command: commands.Command) -> str:
    """Nom conseillé pour l'affichage. Les sous-commandes conservent leur suffixe."""
    preferred = getattr(command, "extras", {}).get("sentrix_preferred_name")
    if preferred:
        return str(preferred)

    qualified = str(getattr(command, "qualified_name", "") or "").strip()
    if not qualified:
        return str(getattr(command, "name", "") or "")

    root, *rest = qualified.split(" ")
    root_preferred = PREFERRED_COMMAND_NAMES.get(root, root)
    return " ".join([root_preferred, *rest]) if rest else root_preferred


def _register_alias(bot: commands.Bot, command: commands.Command, preferred: str) -> bool:
    """Ajoute un alias préfixé sans modifier le nom interne de la commande."""
    if command.parent is not None:
        return False
    original = str(command.name)
    if original in PROTECTED_NAMES or preferred in PROTECTED_NAMES or original == preferred:
        return False

    existing = bot.all_commands.get(preferred)
    if existing is not None and existing is not command:
        logger.warning(
            "Alias commun ignoré : +%s est déjà utilisé par %s (cible souhaitée : %s).",
            preferred,
            getattr(existing, "qualified_name", existing),
            original,
        )
        return False

    aliases = getattr(command, "aliases", None)
    if isinstance(aliases, list) and preferred not in aliases:
        aliases.append(preferred)

    # discord.py résout les commandes texte via all_commands. Garder le même objet Command
    # signifie que tous les checks/permissions/cooldowns historiques continuent à utiliser
    # le nom interne d'origine, donc aucun contournement de sécurité n'est introduit.
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
        # Un alias préfixé n'est pas automatiquement un nouveau nom slash. On n'affiche
        # donc "/ ou +" que lorsque le nom conseillé est déjà le vrai nom slash.
        is_native_name = display == command.qualified_name
        marker = f"/ ou {prefix}" if is_native_name and command.qualified_name in slash_names else prefix
        usage = ""
        if isinstance(command, commands.HybridCommand) and command.clean_params:
            parts = []
            for pname, param in command.clean_params.items():
                parts.append(f"[{pname}]" if param.required else f"({pname})")
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
                alias_text = " ".join(getattr(command, "aliases", []) or [])
                haystack = (
                    f"{command.qualified_name} {preferred_name(command)} {alias_text} "
                    f"{command.description or ''}"
                ).lower()
                if keyword in haystack and id(command) not in seen:
                    seen.add(id(command))
                    results.append((label, command))
        return results

    utility.format_command_line = format_command_line
    utility.search_commands = search_commands

    # +help est remplacé ensuite par help_complete.py dans le loader. Ce module possède
    # son propre générateur de syntaxe : on le rend lui aussi compatible avec les noms
    # conseillés, sans modifier sa catégorisation basée sur les noms internes.
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

    # Conserver les références permet à d'autres patches de diagnostiquer/restaurer le
    # comportement si nécessaire.
    utility._sentrix_original_format_command_line = original_format
    utility._sentrix_original_search_commands = original_search
    _HELP_PATCHED = True
    logger.info("Affichage +help standardisé sur les noms de commandes courants.")


def install(bot: commands.Bot) -> None:
    """À appeler après chaque chargement de cog : les nouveaux cogs sont aliasés au fil de l'eau."""
    added = 0
    for command in list(bot.walk_commands()):
        if command.parent is not None:
            continue
        original = str(command.name)
        preferred = PREFERRED_COMMAND_NAMES.get(original)
        if preferred and _register_alias(bot, command, preferred):
            added += 1

    _patch_help_renderers()
    if added:
        logger.info("%s nom(s) de commande courant(s) ajouté(s) à SentriX.", added)
