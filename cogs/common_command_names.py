"""Ajoute des noms de commandes courts et familiers sans casser les noms internes.

Cette couche améliore aussi l'usage quotidien :
- alias français simples pour les commandes les plus utilisées ;
- résolution robuste des utilisateurs par ID/mention, même hors cache Discord ;
- réponse courte lorsqu'un membre mentionne uniquement SentriX pour retrouver le préfixe.
"""
from __future__ import annotations

import logging
import re
import time

import discord
from discord.ext import commands

import config
from utils import embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.common-command-names")
_HELP_PATCHED = False
_USER_CONVERTER_PATCHED = False
_MENTION_COOLDOWN_SECONDS = 5.0
_MENTION_LAST: dict[int, float] = {}

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

# Alias secondaires : ils ne remplacent PAS le nom affiché dans +help. Ils permettent
# simplement de taper des commandes évidentes en français sans apprendre le nom anglais.
FRENCH_COMMAND_ALIASES: dict[str, tuple[str, ...]] = {
    "help": ("aide",),
    "avatar": ("pp",),
    "userinfo": ("utilisateur",),
    "membercount": ("membres",),
    "poll": ("sondage",),
    "remind": ("rappel",),
    "translate": ("traduire",),
    "weather": ("meteo",),
    "correct": ("corriger",),
    "rewrite": ("reformuler",),
    "summarize": ("resumer",),
    "explain": ("expliquer",),
    "ban": ("bannir",),
    "unban": ("debannir",),
    "kick": ("expulser",),
    "warn": ("avertir",),
    "warnings": ("avertissements",),
    "unwarn": ("retireravertissement",),
    "clearwarnings": ("effaceravertissements",),
    "mute": ("muet",),
    "unmute": ("demuet",),
    "clear": ("effacer",),
    "lock": ("verrouiller",),
    "unlock": ("deverrouiller",),
    "slowmode": ("ralenti",),
    "setup": ("configurer", "configuration"),
    "diagnostic": ("verifierbot",),
    "security-check": ("securite",),
    "balance": ("solde",),
    "inventory": ("inventaire",),
    "daily": ("quotidien",),
    "weekly": ("hebdo",),
    "work": ("travailler",),
    "pay": ("payer",),
    "shop": ("boutique",),
    "level": ("niveau",),
    "leaderboard-levels": ("classementniveaux",),
    "profile": ("profil",),
    "ticket": ("support",),
    "giveaway-list": ("concours",),
    "invite-leaderboard": ("classementinvites",),
    "play": ("jouer",),
    "queue": ("file",),
    "skip": ("suivant",),
    "stop": ("arreter",),
    "nowplaying": ("encours",),
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


def _register_secondary_alias(bot: commands.Bot, command: commands.Command, alias: str) -> bool:
    """Ajoute un alias sans modifier le nom conseillé/affiché de la commande."""
    if command.parent is not None:
        return False
    alias = str(alias or "").casefold().strip()
    if not alias or alias == str(command.name).casefold():
        return False

    existing = bot.all_commands.get(alias)
    if existing is not None:
        return existing is command

    aliases = getattr(command, "aliases", None)
    if isinstance(aliases, list) and alias not in aliases:
        aliases.append(alias)
    bot.all_commands[alias] = command
    return True


def _patch_user_converter() -> None:
    """Accepte un ID/une mention utilisateur même si l'utilisateur n'est pas en cache.

    C'est particulièrement important pour +bl / +unbl : un propriétaire doit pouvoir viser
    un compte qui n'est actuellement dans aucun serveur partagé avec SentriX.
    """
    global _USER_CONVERTER_PATCHED
    if _USER_CONVERTER_PATCHED:
        return

    current = commands.UserConverter.convert
    if getattr(current, "_sentrix_resilient_user_converter", False):
        _USER_CONVERTER_PATCHED = True
        return

    async def convert_with_fetch_fallback(self, ctx: commands.Context, argument: str):
        try:
            return await current(self, ctx, argument)
        except commands.UserNotFound as original_error:
            text = str(argument or "").strip()
            match = re.fullmatch(r"<@!?(\d{15,25})>", text) or re.fullmatch(r"(\d{15,25})", text)
            if not match:
                raise

            user_id = int(match.group(1))
            cached = ctx.bot.get_user(user_id)
            if cached is not None:
                return cached
            try:
                return await ctx.bot.fetch_user(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                raise original_error

    convert_with_fetch_fallback._sentrix_resilient_user_converter = True
    commands.UserConverter.convert = convert_with_fetch_fallback
    _USER_CONVERTER_PATCHED = True
    logger.info("Résolution utilisateur renforcée : ID/mention hors cache pris en charge.")


async def _mention_help(bot: commands.Bot, message: discord.Message) -> None:
    """Quand quelqu'un ping uniquement SentriX, lui indique immédiatement comment commencer."""
    if message.author.bot or bot.user is None:
        return

    content = str(message.content or "").strip()
    if content not in {f"<@{bot.user.id}>", f"<@!{bot.user.id}>"}:
        return

    now = time.monotonic()
    user_id = int(message.author.id)
    if now - _MENTION_LAST.get(user_id, 0.0) < _MENTION_COOLDOWN_SECONDS:
        return
    _MENTION_LAST[user_id] = now
    if len(_MENTION_LAST) > 5000:
        cutoff = now - 60.0
        for key, stamp in list(_MENTION_LAST.items()):
            if stamp < cutoff:
                _MENTION_LAST.pop(key, None)

    prefix = config.DEFAULT_PREFIX
    if message.guild is not None:
        cached = getattr(bot, "prefix_cache", {}).get(message.guild.id)
        if cached:
            prefix = cached
        else:
            try:
                conf = await bot.db.get_guild_config(message.guild.id)
                if conf and conf["prefix"]:
                    prefix = conf["prefix"]
            except Exception:
                pass

    try:
        await panels.envoyer(message.channel, panels.depuis_embed(embeds.neutral("👋 Besoin d'aide ?", f'Mon préfixe sur ce serveur est **`{prefix}`**.\nTapez **`{prefix}help`** pour voir les commandes ou **`{prefix}setup`** pour configurer le serveur.')), allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.HTTPException):
        pass


def _install_mention_listener(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_mention_help_listener", False):
        return

    async def listener(message: discord.Message):
        await _mention_help(bot, message)

    bot.add_listener(listener, "on_message")
    bot._sentrix_mention_help_listener = True
    logger.info("Aide au ping direct activée : @SentriX affiche le préfixe et +help.")


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
    _patch_user_converter()
    _install_mention_listener(bot)

    added = 0
    french_added = 0
    for command in list(bot.walk_commands()):
        if command.parent is not None:
            continue

        preferred = PREFERRED_COMMAND_NAMES.get(str(command.name))
        if preferred and _register_alias(bot, command, preferred):
            added += 1

        for alias in FRENCH_COMMAND_ALIASES.get(str(command.name), ()):
            if _register_secondary_alias(bot, command, alias):
                french_added += 1

    _patch_help_renderers()
    if added:
        logger.info("%s alias de commandes familiers ajoutés.", added)
    if french_added:
        logger.info("%s alias français simples disponibles.", french_added)
