"""Langue par serveur pour les noms de commandes et les interfaces principales SentriX.

Objectifs :
- aucun doublon de commande dans +help : les traductions sont des alias du MEME objet commande ;
- choix Francais / English a l'arrivee du bot, puis modifiable dans +setup ;
- +help affiche uniquement les noms correspondant a la langue du serveur ;
- les anciens alias francais ajoutes globalement sont retires du registre visible ;
- les noms internes restent inchanges pour ne casser ni permissions, ni base, ni slash.

Limite Discord : un nom de commande slash est enregistre au niveau de l'application et ne
peut pas changer dynamiquement selon un reglage propre a chaque serveur. Le choix de langue
pilote donc les commandes prefixees (+), +help, +setup et les surfaces de demarrage. Les
slash continuent d'utiliser leurs noms publies par Discord.
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from typing import Iterable

import discord
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.language-runtime")

LANG_FR = "fr"
LANG_EN = "en"
DEFAULT_LANGUAGE = LANG_FR
_VALID_LANGUAGES = {LANG_FR, LANG_EN}

# Commandes dont une traduction automatique mot-a-mot serait peu naturelle.
EN_COMMAND_NAMES = {
    "bl": "blacklist",
    "blinfo": "blacklist-info",
    "unbl": "unblacklist",
    "editbl": "edit-blacklist",
    "rps": "rock-paper-scissors",
    "aidiag": "ai-diagnostic",
    "aisetup": "ai-setup",
    "banque": "bank",
    "suivi-bot": "bot-tracker",
    "serveur": "server",
}

FR_COMMAND_NAMES = {
    "help": "aide",
    "avatar": "avatar",
    "userinfo": "infos-utilisateur",
    "channelinfo": "infos-salon",
    "membercount": "membres",
    "poll": "sondage",
    "remind": "rappel",
    "reminder-list": "rappels",
    "reminder-cancel": "annuler-rappel",
    "translate": "traduire",
    "weather": "meteo",
    "suggest": "suggestion",
    "report-bug": "signaler-bug",
    "afk": "absent",
    "roll": "lancer-de",
    "choose": "choisir",
    "ai": "ia",
    "summarize": "resumer",
    "image-prompt": "prompt-image",
    "explain": "expliquer",
    "rewrite": "reformuler",
    "fact-check": "verifier-fait",
    "improve": "ameliorer",
    "correct": "corriger",
    "ai-translate": "traduire-ia",
    "balance": "solde",
    "economy": "economie",
    "daily": "quotidien",
    "weekly": "hebdomadaire",
    "work": "travailler",
    "rob": "voler",
    "pay": "payer",
    "economyleaderboard": "classement-argent",
    "shop": "boutique",
    "buy": "acheter",
    "inventory": "inventaire",
    "sell": "vendre",
    "gamble": "parier",
    "deposit": "deposer",
    "withdraw": "retirer",
    "stats": "statistiques",
    "level": "niveau",
    "leaderboard-levels": "classement-niveaux",
    "profile": "profil",
    "set-bio": "definir-bio",
    "repleaderboard": "classement-reputation",
    "voice-time": "temps-vocal",
    "rps": "pierre-feuille-ciseaux",
    "guess-number": "deviner-nombre",
    "tictactoe": "morpion",
    "hangman": "pendu",
    "math-quiz": "quiz-maths",
    "join": "rejoindre-vocal",
    "leave": "quitter-vocal",
    "play": "jouer",
    "resume": "reprendre",
    "skip": "suivant",
    "stop": "arreter",
    "queue": "file",
    "nowplaying": "en-cours",
    "loop": "boucle",
    "shuffle": "melanger",
    "remove-from-queue": "retirer-file",
    "clear-queue": "vider-file",
    "playlist-save": "sauvegarder-playlist",
    "playlist-load": "charger-playlist",
    "giveaway-list": "concours",
    "giveaway-create": "creer-concours",
    "giveaway-end": "terminer-concours",
    "giveaway-reroll": "retirer-gagnant",
    "giveaway-cancel": "annuler-concours",
    "event-join": "rejoindre-evenement",
    "event-leave": "quitter-evenement",
    "event-list": "evenements",
    "event-create": "creer-evenement",
    "event-cancel": "annuler-evenement",
    "tournament-join": "rejoindre-tournoi",
    "tournament-list": "tournois",
    "tournament-create": "creer-tournoi",
    "tournament-start": "demarrer-tournoi",
    "invite-leaderboard": "classement-invitations",
    "invited-by": "invite-par",
    "ban": "bannir",
    "tempban": "bannir-temporairement",
    "unban": "debannir",
    "kick": "expulser",
    "mute": "rendre-muet",
    "unmute": "retirer-muet",
    "warn": "avertir",
    "unwarn": "retirer-avertissement",
    "warnings": "avertissements",
    "clearwarnings": "effacer-avertissements",
    "case": "dossier",
    "modhistory": "historique-moderation",
    "quarantine": "quarantaine",
    "unquarantine": "retirer-quarantaine",
    "clear": "effacer-messages",
    "slowmode": "mode-lent",
    "lock": "verrouiller",
    "unlock": "deverrouiller",
    "hide": "cacher",
    "show": "afficher",
    "nickname": "surnom",
    "resetnick": "reinitialiser-surnom",
    "disconnect": "deconnecter",
    "giverole": "donner-role",
    "removerole": "retirer-role",
    "permission-audit": "audit-permissions",
    "security-check": "verifier-securite",
    "security-level": "niveau-securite",
    "server-backup": "sauvegarder-serveur",
    "server-restore": "restaurer-serveur",
    "setup": "configurer",
    "config-view": "voir-configuration",
    "config-reset": "reinitialiser-configuration",
    "create-server": "creer-serveur",
    "delete-channel": "supprimer-salon",
    "logs-status": "etat-logs",
    "logsetup": "configurer-logs",
    "create-logs": "creer-logs",
    "rolepanel": "panneau-roles",
    "rolepanel-refresh": "actualiser-roles",
    "verify-panel": "panneau-verification",
    "embed": "embed",
    "announce": "annoncer",
    "designsetup": "design",
    "bot-status": "etat-bot",
    "server-growth": "croissance-serveur",
    "command-stats": "statistiques-commandes",
    "diagnostic": "diagnostic",
    "bl": "liste-noire",
    "blinfo": "infos-liste-noire",
    "unbl": "retirer-liste-noire",
    "editbl": "modifier-liste-noire",
    "sync": "synchroniser",
    "syncguild": "synchroniser-serveur",
    "setstatus": "definir-statut",
    "status-rotate": "rotation-statut",
    "bot-servers": "serveurs-bot",
    "bot-leave": "quitter-serveur",
    "suivi-bot": "suivi-bot",
}

FR_TOKEN_MAP = {
    "set": "definir", "add": "ajouter", "remove": "retirer", "delete": "supprimer",
    "clear": "effacer", "create": "creer", "reset": "reinitialiser", "list": "liste",
    "status": "etat", "server": "serveur", "channel": "salon", "channels": "salons",
    "member": "membre", "members": "membres", "user": "utilisateur", "users": "utilisateurs",
    "role": "role", "roles": "roles", "welcome": "bienvenue", "goodbye": "depart",
    "message": "message", "messages": "messages", "level": "niveau", "levels": "niveaux",
    "suggest": "suggestion", "announce": "annonce", "ticket": "ticket", "tickets": "tickets",
    "form": "formulaire", "limit": "limite", "close": "fermer", "security": "securite",
    "backup": "sauvegarde", "restore": "restaurer", "whitelist": "liste-blanche",
    "blacklist": "liste-noire", "history": "historique", "permission": "permission",
    "permissions": "permissions", "economy": "economie", "money": "argent", "shop": "boutique",
    "profile": "profil", "voice": "vocal", "time": "temps", "game": "jeu", "games": "jeux",
    "guess": "deviner", "number": "nombre", "math": "maths", "play": "jouer", "queue": "file",
    "playlist": "playlist", "save": "sauvegarder", "load": "charger", "event": "evenement",
    "tournament": "tournoi", "invite": "invitation", "invites": "invitations",
    "notification": "notification", "notifications": "notifications", "help": "aide",
    "translate": "traduire", "weather": "meteo", "poll": "sondage", "reminder": "rappel",
    "cancel": "annuler", "info": "infos", "config": "configuration", "check": "verifier",
    "enable": "activer", "disable": "desactiver", "ignore": "ignorer", "unignore": "ne-plus-ignorer",
    "lockdown": "verrouillage", "unlock": "deverrouiller", "domain": "domaine",
}

EN_TOKEN_MAP = {
    "serveur": "server", "salon": "channel", "salons": "channels", "membre": "member",
    "membres": "members", "utilisateur": "user", "utilisateurs": "users", "niveau": "level",
    "niveaux": "levels", "banque": "bank", "securite": "security", "bienvenue": "welcome",
    "depart": "goodbye", "evenement": "event", "tournoi": "tournament", "vocal": "voice",
    "temps": "time", "historique": "history", "configuration": "config", "statistiques": "stats",
}

CATEGORY_I18N = {
    "ai": ("Intelligence artificielle", "Artificial intelligence"),
    "information": ("Informations", "Information"),
    "utility": ("Outils pratiques", "Utilities"),
    "economy": ("Economie et boutique", "Economy & shop"),
    "levels": ("Niveaux et reputation", "Levels & reputation"),
    "games": ("Mini-jeux", "Mini-games"),
    "music": ("Musique", "Music"),
    "events": ("Concours et evenements", "Giveaways & events"),
    "social": ("Invitations et notifications", "Invites & notifications"),
    "tickets": ("Tickets et support", "Tickets & support"),
    "sanctions": ("Sanctions et dossiers", "Sanctions & cases"),
    "moderation": ("Moderation du serveur", "Server moderation"),
    "security": ("AutoMod et securite", "AutoMod & security"),
    "configuration": ("Configuration et logs", "Configuration & logs"),
    "server": ("Serveur et structure", "Server & structure"),
    "roles": ("Roles et verification", "Roles & verification"),
    "embeds": ("Embeds, annonces et design", "Embeds, announcements & design"),
    "stats": ("Statistiques et diagnostic", "Statistics & diagnostics"),
    "owner": ("Proprietaire du bot", "Bot owner"),
    "other": ("Autres commandes", "Other commands"),
}

EN_SUMMARY = {
    "help": "Show the command center and detailed command help.",
    "setup": "Open the server configuration center.",
    "ban": "Ban a member from the server.", "tempban": "Temporarily ban a member.",
    "unban": "Unban a user.", "kick": "Kick a member from the server.",
    "mute": "Temporarily restrict a member from speaking.", "unmute": "Remove a member timeout.",
    "warn": "Add a warning to a member.", "warnings": "Show a member's warnings.",
    "clear": "Delete several messages from the current channel.",
    "ticket": "Open a support ticket.", "ticketsetup": "Configure the ticket system.",
    "balance": "Show your current balance.", "shop": "Open the server shop.",
    "daily": "Claim the daily reward.", "weekly": "Claim the weekly reward.",
    "level": "Show your current level and XP.", "profile": "Show your community profile.",
    "play": "Play music in your voice channel.", "queue": "Show the music queue.",
    "poll": "Create a Discord poll.", "weather": "Show the weather for a location.",
    "translate": "Translate text into another language.",
    "ai": "Talk with SentriX AI.", "sentrix": "Ask SentriX a question.",
    "image": "Generate an image from a prompt.",
    "bl": "Block a user from using SentriX globally.",
}

PARAM_FR = {
    "member": "membre", "membre": "membre", "user": "utilisateur", "utilisateur": "utilisateur",
    "role": "role", "channel": "salon", "salon": "salon", "reason": "raison", "raison": "raison",
    "duration": "duree", "duree": "duree", "amount": "montant", "montant": "montant",
    "text": "texte", "texte": "texte", "message": "message", "level": "niveau", "niveau": "niveau",
    "command": "commande", "commande": "commande", "name": "nom", "nom": "nom", "query": "recherche",
}
PARAM_EN = {
    "membre": "member", "member": "member", "utilisateur": "user", "user": "user",
    "role": "role", "salon": "channel", "channel": "channel", "raison": "reason", "reason": "reason",
    "duree": "duration", "duration": "duration", "montant": "amount", "amount": "amount",
    "texte": "text", "text": "text", "message": "message", "niveau": "level", "level": "level",
    "commande": "command", "command": "command", "nom": "name", "name": "name", "recherche": "query",
}

SETUP_EN_REPLACEMENTS = (
    ("Centre de controle", "Control Center"), ("Centre de contrôle", "Control Center"),
    ("Base du serveur", "Server basics"), ("Roles automatiques", "Automatic roles"),
    ("Rôles automatiques", "Automatic roles"), ("Tickets & support", "Tickets & support"),
    ("Salons utiles", "Useful channels"), ("Niveaux & recompenses", "Levels & rewards"),
    ("Niveaux & récompenses", "Levels & rewards"), ("Logs & surveillance", "Logs & monitoring"),
    ("Acces administrateurs", "Administrator access"), ("Accès administrateurs", "Administrator access"),
    ("Protection AutoMod", "AutoMod protection"), ("Verification finale", "Final check"),
    ("Vérification finale", "Final check"), ("Etat de la configuration", "Configuration status"),
    ("État de la configuration", "Configuration status"), ("A faire maintenant", "Next actions"),
    ("À faire maintenant", "Next actions"), ("Comment l'utiliser", "How to use it"),
    ("Ce que tu regles ici", "What you configure here"), ("Ce que tu règles ici", "What you configure here"),
    ("Conseil", "Tip"), ("Resume", "Summary"), ("Résumé", "Summary"),
    ("Historique", "History"), ("Fermer", "Close"), ("Ouvrir le dashboard web", "Open web dashboard"),
    ("Tout est enregistre", "Everything is saved"), ("Tout est enregistré", "Everything is saved"),
    ("Modifications en attente", "Unsaved changes"), ("Serveur", "Server"),
    ("Choisis ce que tu veux configurer", "Choose what you want to configure"),
    ("Selectionne une option", "Select an option"), ("Sélectionne une option", "Select an option"),
    ("Configure", "Configure"), ("configurer", "configure"), ("reglages", "settings"), ("réglages", "settings"),
    ("salons", "channels"), ("roles", "roles"), ("rôles", "roles"), ("serveur", "server"),
    ("membres", "members"), ("securite", "security"), ("sécurité", "security"),
)


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _slug(value: str) -> str:
    value = _strip_accents(value).casefold().strip().replace("_", "-")
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "commande"


def _translate_tokens(name: str, mapping: dict[str, str]) -> str:
    pieces = str(name or "").replace("_", "-").split("-")
    translated = [mapping.get(_slug(piece), _slug(piece)) for piece in pieces if piece]
    return "-".join(translated) if translated else _slug(name)


def localized_component(command: commands.Command, language: str) -> str:
    name = str(getattr(command, "name", "") or "commande")
    if language == LANG_EN:
        if name in EN_COMMAND_NAMES:
            return _slug(EN_COMMAND_NAMES[name])
        # Les alias « preferes » existants sont deja propres en anglais pour les racines.
        if command.parent is None:
            try:
                from . import common_command_names
                preferred = common_command_names.PREFERRED_COMMAND_NAMES.get(name)
                if preferred:
                    return _slug(preferred)
            except Exception:
                pass
        return _translate_tokens(name, EN_TOKEN_MAP)

    if name in FR_COMMAND_NAMES:
        return _slug(FR_COMMAND_NAMES[name])
    return _translate_tokens(name, FR_TOKEN_MAP)


def localized_command_name(command: commands.Command, language: str) -> str:
    chain: list[commands.Command] = []
    current: commands.Command | None = command
    while current is not None:
        chain.append(current)
        current = getattr(current, "parent", None)
    chain.reverse()
    return " ".join(localized_component(item, language) for item in chain)


def _category_text(category, language: str) -> tuple[str, str]:
    names = CATEGORY_I18N.get(getattr(category, "key", "other"), CATEGORY_I18N["other"])
    name = names[1] if language == LANG_EN else names[0]
    summary = getattr(category, "summary", "")
    if language == LANG_EN:
        generic = {
            "ai": "AI, writing, translation and image tools.", "information": "Server, member and bot information.",
            "utility": "Everyday utilities and quick tools.", "economy": "Money, bank, shop and inventory.",
            "levels": "XP, profiles, leaderboards and reputation.", "games": "Quick games and multiplayer activities.",
            "music": "Playback, queue, volume and playlists.", "events": "Giveaways, events and tournaments.",
            "social": "Invites, welcome tools and notifications.", "tickets": "Support tickets and ticket configuration.",
            "sanctions": "Bans, timeouts, warnings and moderation cases.", "moderation": "Messages, channels, roles and voice moderation.",
            "security": "Anti-raid, anti-nuke, AutoMod and security tools.", "configuration": "Server setup, logs and bot settings.",
            "server": "Server structure and bulk management.", "roles": "Role panels, verification and role tools.",
            "embeds": "Embeds, announcements and appearance.", "stats": "Bot statistics and diagnostics.",
            "owner": "Global owner-only bot management.", "other": "Other active commands.",
        }
        summary = generic.get(getattr(category, "key", "other"), 'Activez SentriX commands.')
    return name, summary


async def _ensure_table(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_language_table_ready", False):
        return
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS guild_language_settings (
            guild_id INTEGER PRIMARY KEY,
            language TEXT NOT NULL DEFAULT 'fr',
            updated_at INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    bot._sentrix_language_table_ready = True
    if not hasattr(bot, "guild_language_cache"):
        bot.guild_language_cache = {}


async def get_language(bot: commands.Bot, guild_id: int | None) -> str:
    if guild_id is None:
        return DEFAULT_LANGUAGE
    await _ensure_table(bot)
    cached = bot.guild_language_cache.get(int(guild_id))
    if cached in _VALID_LANGUAGES:
        return cached
    row = await bot.db.fetchone(
        "SELECT language FROM guild_language_settings WHERE guild_id = ?",
        (int(guild_id),),
    )
    language = str(row["language"]) if row and row["language"] in _VALID_LANGUAGES else DEFAULT_LANGUAGE
    bot.guild_language_cache[int(guild_id)] = language
    return language


def cached_language(bot: commands.Bot, guild_id: int | None) -> str:
    if guild_id is None:
        return DEFAULT_LANGUAGE
    return getattr(bot, "guild_language_cache", {}).get(int(guild_id), DEFAULT_LANGUAGE)


async def set_language(bot: commands.Bot, guild_id: int, language: str) -> None:
    language = language if language in _VALID_LANGUAGES else DEFAULT_LANGUAGE
    await _ensure_table(bot)
    try:
        from database.db import now
        timestamp = int(now())
    except Exception:
        timestamp = int(time.time())
    await bot.db.execute(
        """
        INSERT INTO guild_language_settings (guild_id, language, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET language = excluded.language, updated_at = excluded.updated_at
        """,
        (int(guild_id), language, timestamp),
    )
    bot.guild_language_cache[int(guild_id)] = language


def _register_alias(bot: commands.Bot, command: commands.Command, alias: str) -> bool:
    alias = _slug(alias)
    if not alias or alias == command.name:
        return False
    parent = getattr(command, "parent", None)
    registry = parent.all_commands if parent is not None else bot.all_commands
    existing = registry.get(alias)
    if existing is not None:
        return existing is command
    registry[alias] = command
    aliases = getattr(command, "aliases", None)
    if isinstance(aliases, list) and alias not in aliases:
        aliases.append(alias)
    return True


def _remove_old_french_aliases(bot: commands.Bot) -> None:
    """Retire les alias FR de la passe precedente avant d'installer le vrai mode langue."""
    try:
        from . import common_command_names
    except Exception:
        return

    old_map = dict(getattr(common_command_names, "FRENCH_COMMAND_ALIASES", {}) or {})
    for root_name, aliases in old_map.items():
        command = bot.get_command(root_name)
        if command is None:
            continue
        for alias in aliases:
            key = str(alias).casefold().strip()
            if bot.all_commands.get(key) is command:
                bot.all_commands.pop(key, None)
            if isinstance(getattr(command, "aliases", None), list):
                while key in command.aliases:
                    command.aliases.remove(key)
    # Les prochains chargements de cogs ne doivent plus les recreer.
    common_command_names.FRENCH_COMMAND_ALIASES = {}

    # L'ancien listener @SentriX repondait toujours en francais : on le remplace plus bas.
    for listener in list(getattr(bot, "extra_events", {}).get("on_message", [])):
        if getattr(listener, "__module__", "") == "cogs.common_command_names" and "listener" in getattr(listener, "__qualname__", ""):
            bot.remove_listener(listener, "on_message")
    common_command_names._install_mention_listener = lambda _bot: None


def install_language_aliases(bot: commands.Bot) -> int:
    added = 0
    collisions: list[str] = []
    _remove_old_french_aliases(bot)
    for command in list(bot.walk_commands()):
        for language in (LANG_FR, LANG_EN):
            alias = localized_component(command, language)
            parent = getattr(command, "parent", None)
            registry = parent.all_commands if parent is not None else bot.all_commands
            existing = registry.get(alias)
            if existing is not None and existing is not command:
                collisions.append(f"{command.qualified_name}->{alias}")
                continue
            if _register_alias(bot, command, alias):
                added += 1
    if collisions:
        logger.warning("Alias langue ignores a cause de collisions : %s", ", ".join(collisions[:12]))
    return added


def _summary(command: commands.Command, language: str) -> str:
    root = str((command.root_parent or command).name)
    if language == LANG_EN:
        if root in EN_SUMMARY:
            return EN_SUMMARY[root]
        human = localized_command_name(command, LANG_EN).replace("-", " ")
        return f"Use this command to manage {human}."
    try:
        from . import command_clarity
        return command_clarity.friendly_summary(command)
    except Exception:
        text = str(getattr(command, "description", "") or "").strip()
        return text or "Utilise cette commande pour gerer cette fonction de SentriX."


def _title(command: commands.Command, language: str) -> str:
    if language == LANG_EN:
        return localized_command_name(command, LANG_EN).replace("-", " ").title()
    try:
        from . import command_clarity
        return command_clarity.friendly_title(command)
    except Exception:
        return localized_command_name(command, LANG_FR).replace("-", " ").capitalize()


def _param_name(name: str, language: str) -> str:
    key = _strip_accents(str(name or "value")).casefold().replace("-", "_")
    mapping = PARAM_EN if language == LANG_EN else PARAM_FR
    return mapping.get(key, key.replace("_", " "))


def _command_usage(command: commands.Command, prefix: str, language: str) -> str:
    parts = [f"{prefix}{localized_command_name(command, language)}"]
    for name, parameter in getattr(command, "clean_params", {}).items():
        if name in {"ctx", "context", "interaction", "self"}:
            continue
        display = _param_name(name, language)
        parts.append(f"<{display}>" if getattr(parameter, "required", False) else f"[{display}]")
    return " ".join(parts)


def _command_line(utility, command: commands.Command, prefix: str, language: str, number: int | None = None) -> str:
    index = f"`{number:02d}` " if number is not None else ""
    lock = "🔒 " if utility.is_staff_command(command) else ""
    usage = _command_usage(command, prefix, language)
    return f"{index}{lock}**`{usage}`**\n└ {_summary(command, language)}"


def _help_entries(bot: commands.Bot, is_staff: bool):
    from . import help_complete, utility
    return help_complete._category_entries(utility, bot, is_staff)


def _help_home(bot: commands.Bot, guild: discord.Guild | None, prefix: str, is_staff: bool, language: str) -> discord.Embed:
    entries = _help_entries(bot, is_staff)
    total = sum(len(items) for _, items in entries)
    server = guild.name if guild else ("this server" if language == LANG_EN else "ce serveur")
    if language == LANG_EN:
        e = embeds.brand(
            "✦ SentriX Command Center",
            f"Commands for **{server}** are displayed in English. Choose a category below or search for a command.\n\n"
            f"**{total} active commands** • prefix `{prefix}`",
        )
        section_names = {"essential": "⭐ Essentials", "community": "🎉 Community", "staff": "🛡️ Administration"}
        quick_name = "⌕ Quick navigation"
        quick_value = f"`{prefix}help ban` → command details\n**Search** → find a command by name\nLanguage: **English**"
    else:
        e = embeds.brand(
            "✦ Centre de commandes SentriX",
            f'Les commandes de **{server}** sont affichees en francais. Choisissez une categorie ou recherche une commande.\n\n**{total} commandes actives** • prefixe `{prefix}`',
        )
        section_names = {"essential": "⭐ Essentiels", "community": "🎉 Communaute", "staff": "🛡️ Administration"}
        quick_name = "⌕ Navigation rapide"
        quick_value = f"`{prefix}aide bannir` → detail d'une commande\n**Rechercher** → trouver une commande par nom\nLangue : **Francais**"
    if bot.user:
        e.set_thumbnail(url=bot.user.display_avatar.url)
    for section in ("essential", "community", "staff"):
        rows = []
        for category, commands_list in entries:
            if getattr(category, "section", "") != section:
                continue
            name, _ = _category_text(category, language)
            rows.append(f"{category.emoji} **{name}** · `{len(commands_list)}`")
        if rows:
            e.add_field(name=section_names[section], value="\n".join(rows), inline=section != "staff")
    e.add_field(name=quick_name, value=quick_value, inline=False)
    return e


def _build_category_pages(bot: commands.Bot, prefix: str, language: str, category, commands_list) -> list[discord.Embed]:
    from . import utility
    name, summary = _category_text(category, language)
    chunks = [commands_list[i:i + 10] for i in range(0, len(commands_list), 10)] or [[]]
    pages = []
    for page_no, chunk in enumerate(chunks, start=1):
        lines = [_command_line(utility, cmd, prefix, language) for cmd in chunk]
        e = embeds.brand(f"{category.emoji} {name}", summary + "\n\n" + "\n\n".join(lines))
        if language == LANG_EN:
            e.set_footer(text=f"Page {page_no}/{len(chunks)} • {len(commands_list)} commands • <required> [optional]")
        else:
            e.set_footer(text=f"Page {page_no}/{len(chunks)} • {len(commands_list)} commandes • <obligatoire> [facultatif]")
        pages.append(e)
    return pages


def resolve_localized_command(bot: commands.Bot, query: str, language: str) -> commands.Command | None:
    query = " ".join(str(query or "").casefold().strip().split())
    direct = bot.get_command(query)
    if direct is not None:
        return direct
    normalized = _strip_accents(query)
    for command in bot.walk_commands():
        if _strip_accents(localized_command_name(command, language).casefold()) == normalized:
            return command
    return None


class LanguageHelpSearchModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool, language: str, author_id: int):
        super().__init__(title="Search a command" if language == LANG_EN else "Rechercher une commande")
        self.bot = bot
        self.prefix = prefix
        self.is_staff = is_staff
        self.language = language
        self.author_id = author_id
        self.query = discord.ui.TextInput(
            label="Name or keyword" if language == LANG_EN else "Nom ou mot-cle",
            placeholder="ticket, ban, music..." if language == LANG_EN else "ticket, bannir, musique...",
            max_length=60,
        )
        self.add_item(self.query)

    async def on_submit(self, interaction: discord.Interaction):
        from . import utility, help_complete
        needle = _strip_accents(str(self.query.value).casefold())
        results = []
        for command in help_complete._registered_commands(utility, self.bot, self.is_staff):
            haystack = " ".join((
                command.qualified_name,
                localized_command_name(command, self.language),
                localized_command_name(command, LANG_FR),
                localized_command_name(command, LANG_EN),
                _summary(command, self.language),
            ))
            if needle in _strip_accents(haystack.casefold()):
                results.append(command)
        if not results:
            text = "No command found." if self.language == LANG_EN else "Aucune commande trouvee."
            return await interaction.response.edit_message(
                embed=embeds.warning(text),
                view=LanguageHelpHomeView(self.bot, self.prefix, self.is_staff, self.language, self.author_id),
            )
        chunks = [results[i:i + 10] for i in range(0, len(results), 10)]
        pages = []
        for i, chunk in enumerate(chunks, start=1):
            lines = [_command_line(utility, cmd, self.prefix, self.language) for cmd in chunk]
            title = "⌕ Search results" if self.language == LANG_EN else "⌕ Resultats de recherche"
            e = embeds.brand(title, "\n\n".join(lines))
            e.set_footer(text=f"Page {i}/{len(chunks)} • {len(results)}")
            pages.append(e)
        home = _help_home(self.bot, interaction.guild, self.prefix, self.is_staff, self.language)
        await interaction.response.edit_message(
            embed=pages[0],
            view=LanguageHelpPagesView(self.bot, self.prefix, self.is_staff, self.language, self.author_id, pages, home),
        )


class LanguageHelpSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool, language: str, author_id: int):
        self.bot = bot
        self.prefix = prefix
        self.is_staff = is_staff
        self.language = language
        self.author_id = author_id
        self.entries = _help_entries(bot, is_staff)
        options = []
        for category, commands_list in self.entries:
            name, summary = _category_text(category, language)
            options.append(discord.SelectOption(
                label=f"{category.emoji} {name}"[:100],
                value=category.key,
                description=f"{len(commands_list)} • {summary}"[:100],
            ))
        super().__init__(
            placeholder="Choose a category..." if language == LANG_EN else 'Choisissez une categorie...',
            options=options[:25],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            text = "Only the person who opened help can use this menu." if self.language == LANG_EN else "Seule la personne qui a ouvert l'aide peut utiliser ce menu."
            return await interaction.response.send_message(text, ephemeral=True)
        selected = self.values[0]
        matching = next(((cat, cmds) for cat, cmds in self.entries if cat.key == selected), None)
        if not matching:
            return await interaction.response.defer()
        pages = _build_category_pages(self.bot, self.prefix, self.language, *matching)
        home = _help_home(self.bot, interaction.guild, self.prefix, self.is_staff, self.language)
        await interaction.response.edit_message(
            embed=pages[0],
            view=LanguageHelpPagesView(self.bot, self.prefix, self.is_staff, self.language, self.author_id, pages, home),
        )


class LanguageHelpHomeView(discord.ui.View):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool, language: str, author_id: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.prefix = prefix
        self.is_staff = is_staff
        self.language = language
        self.author_id = author_id
        self.add_item(LanguageHelpSelect(bot, prefix, is_staff, language, author_id))
        search = discord.ui.Button(
            label="⌕ Search" if language == LANG_EN else "⌕ Rechercher",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        async def search_callback(interaction: discord.Interaction):
            if interaction.user.id != self.author_id:
                return await interaction.response.send_message("Not your menu." if language == LANG_EN else "Ce menu ne t'appartient pas.", ephemeral=True)
            await interaction.response.send_modal(LanguageHelpSearchModal(bot, prefix, is_staff, language, author_id))
        search.callback = search_callback
        self.add_item(search)


class LanguageHelpPagesView(discord.ui.View):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool, language: str, author_id: int, pages: list[discord.Embed], home_embed: discord.Embed):
        super().__init__(timeout=180)
        self.bot = bot
        self.prefix = prefix
        self.is_staff = is_staff
        self.language = language
        self.author_id = author_id
        self.pages = pages
        self.home_embed = home_embed
        self.index = 0
        self.add_item(LanguageHelpSelect(bot, prefix, is_staff, language, author_id))
        prev = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, row=1)
        home = discord.ui.Button(label="Home" if language == LANG_EN else "Accueil", emoji="🏠", style=discord.ButtonStyle.primary, row=1)
        nxt = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary, row=1)
        search = discord.ui.Button(label="Search" if language == LANG_EN else "Rechercher", emoji="🔎", style=discord.ButtonStyle.secondary, row=2)

        async def previous(interaction: discord.Interaction):
            if interaction.user.id != author_id:
                return await interaction.response.send_message("Not your menu." if language == LANG_EN else "Ce menu ne t'appartient pas.", ephemeral=True)
            self.index = max(0, self.index - 1)
            await interaction.response.edit_message(embed=self.pages[self.index], view=self)
        async def go_home(interaction: discord.Interaction):
            if interaction.user.id != author_id:
                return await interaction.response.send_message("Not your menu." if language == LANG_EN else "Ce menu ne t'appartient pas.", ephemeral=True)
            await interaction.response.edit_message(embed=self.home_embed, view=LanguageHelpHomeView(bot, prefix, is_staff, language, author_id))
        async def next_page(interaction: discord.Interaction):
            if interaction.user.id != author_id:
                return await interaction.response.send_message("Not your menu." if language == LANG_EN else "Ce menu ne t'appartient pas.", ephemeral=True)
            self.index = min(len(self.pages) - 1, self.index + 1)
            await interaction.response.edit_message(embed=self.pages[self.index], view=self)
        async def do_search(interaction: discord.Interaction):
            if interaction.user.id != author_id:
                return await interaction.response.send_message("Not your menu." if language == LANG_EN else "Ce menu ne t'appartient pas.", ephemeral=True)
            await interaction.response.send_modal(LanguageHelpSearchModal(bot, prefix, is_staff, language, author_id))
        prev.callback = previous; home.callback = go_home; nxt.callback = next_page; search.callback = do_search
        self.add_item(prev); self.add_item(home); self.add_item(nxt); self.add_item(search)


async def _localized_help_callback(cog, ctx: commands.Context, *, commande: str = None):
    bot = cog.bot
    language = await get_language(bot, ctx.guild.id if ctx.guild else None)
    conf = await bot.db.get_guild_config(ctx.guild.id) if ctx.guild else None
    prefix = conf["prefix"] if conf and conf["prefix"] else "+"
    is_staff = await cog._user_is_staff(ctx)

    if commande:
        from . import utility, help_complete
        cmd = resolve_localized_command(bot, commande, language)
        if cmd is None or (utility.is_staff_command(cmd) and not is_staff):
            if language == LANG_EN:
                text = f"I can't find `{commande}` or you don't have access to it. Use `{prefix}help` to return to the command center."
            else:
                text = f"Je ne trouve pas `{commande}` ou tu n'as pas acces a cette commande. Utilise `{prefix}aide` pour revenir au catalogue."
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(text)))

        category = help_complete._category_for(cmd)
        category_name, _ = _category_text(category, language)
        e = embeds.brand(f"📘 {_title(cmd, language)}", _summary(cmd, language))
        if bot.user:
            e.set_thumbnail(url=bot.user.display_avatar.url)
        if language == LANG_EN:
            e.add_field(name="⌨️ Syntax", value=f"`{_command_usage(cmd, prefix, language)}`", inline=False)
            params = []
            for name, parameter in getattr(cmd, "clean_params", {}).items():
                if name in {"ctx", "context", "interaction", "self"}: continue
                params.append(f"• **{_param_name(name, language)}** — {'required' if getattr(parameter, 'required', False) else 'optional'}")
            e.add_field(name="🧩 Parameters", value="\n".join(params) if params else "No parameters.", inline=False)
            e.add_field(name="🔐 Access", value=f"{category.emoji} {category_name} • {'Staff only' if utility.is_staff_command(cmd) else 'Members'}", inline=False)
            e.set_footer(text="Only one command name is displayed for the language selected on this server.")
        else:
            e.add_field(name="⌨️ Syntaxe", value=f"`{_command_usage(cmd, prefix, language)}`", inline=False)
            params = []
            for name, parameter in getattr(cmd, "clean_params", {}).items():
                if name in {"ctx", "context", "interaction", "self"}: continue
                params.append(f"• **{_param_name(name, language)}** — {'obligatoire' if getattr(parameter, 'required', False) else 'facultatif'}")
            e.add_field(name="🧩 Parametres", value="\n".join(params) if params else "Aucun parametre.", inline=False)
            e.add_field(name="🔐 Acces", value=f"{category.emoji} {category_name} • {'Staff uniquement' if utility.is_staff_command(cmd) else 'Membres'}", inline=False)
            e.set_footer(text="Un seul nom est affiche pour chaque commande selon la langue du serveur.")
        return await panels.envoyer(ctx, panels.depuis_embed(e))

    home = _help_home(bot, ctx.guild, prefix, is_staff, language)
    return await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(home), LanguageHelpHomeView(bot, prefix, is_staff, language, ctx.author.id)))


def _install_help_patch(bot: commands.Bot) -> None:
    help_command = bot.get_command("help")
    if help_command is None or getattr(help_command, "_sentrix_language_help", False):
        return
    original = help_command.callback
    _localized_help_callback.__name__ = getattr(original, "__name__", "help_cmd")
    _localized_help_callback.__doc__ = getattr(original, "__doc__", None)
    help_command.callback = _localized_help_callback
    help_command._sentrix_language_help = True
    logger.info("+help localise installe : un seul nom de commande affiche selon la langue du serveur.")


def _english_setup_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    for source, target in SETUP_EN_REPLACEMENTS:
        text = text.replace(source, target)
    return text


def _translate_setup_embed(embed: discord.Embed) -> discord.Embed:
    embed.title = _english_setup_text(embed.title)
    embed.description = _english_setup_text(embed.description)
    for index, field in enumerate(list(embed.fields)):
        embed.set_field_at(index, name=_english_setup_text(field.name), value=_english_setup_text(field.value), inline=field.inline)
    if embed.footer and embed.footer.text:
        embed.set_footer(text=_english_setup_text(embed.footer.text), icon_url=embed.footer.icon_url or None)
    return embed


def _install_setup_patch(bot: commands.Bot) -> None:
    try:
        from . import configuration
    except Exception:
        return
    view_cls = getattr(configuration, "SetupView", None)
    if view_cls is None or getattr(view_cls, "_sentrix_language_patch", False):
        return

    original_build = view_cls.build_embed
    original_render = view_cls.render_page

    async def build_embed(self):
        embed = await original_build(self)
        language = await get_language(self.bot, self.guild_id)
        if language == LANG_EN:
            _translate_setup_embed(embed)
        if getattr(self, "page", None) == -1:
            label = "English" if language == LANG_EN else "Francais"
            embed.add_field(
                name="🌐 Language" if language == LANG_EN else "🌐 Langue",
                value=(f"Current language: **{label}**" if language == LANG_EN else f"Langue actuelle : **{label}**"),
                inline=False,
            )
        return embed

    def render_page(self):
        original_render(self)
        language = cached_language(self.bot, self.guild_id)
        if language == LANG_EN:
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.label = _english_setup_text(item.label)
                elif isinstance(item, discord.ui.Select):
                    item.placeholder = _english_setup_text(item.placeholder)
                    for option in item.options:
                        option.label = _english_setup_text(option.label)
                        option.description = _english_setup_text(option.description)
        if getattr(self, "page", None) != -1:
            return
        selector = discord.ui.Select(
            placeholder="🌐 Language / Langue",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="🇫🇷 Francais", value=LANG_FR, description="Noms de commandes et interfaces en francais"),
                discord.SelectOption(label="🇬🇧 English", value=LANG_EN, description="Command names and interfaces in English"),
            ],
            row=3,
        )
        async def language_callback(interaction: discord.Interaction):
            if not interaction.user.guild_permissions.administrator and interaction.user.id != interaction.guild.owner_id:
                return await interaction.response.send_message(
                    "Administrator permission required. / Permission Administrateur requise.", ephemeral=True
                )
            await set_language(self.bot, self.guild_id, selector.values[0])
            self.render_page()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        selector.callback = language_callback
        self.add_item(selector)

    view_cls.build_embed = build_embed
    view_cls.render_page = render_page
    view_cls._sentrix_language_patch = True
    logger.info("Selecteur de langue ajoute a +setup.")


class LanguageChoiceView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

        fr = discord.ui.Button(label="Francais", emoji="🇫🇷", style=discord.ButtonStyle.primary, custom_id="sentrix:language:fr")
        en = discord.ui.Button(label="English", emoji="🇬🇧", style=discord.ButtonStyle.secondary, custom_id="sentrix:language:en")

        async def choose(interaction: discord.Interaction, language: str):
            if interaction.guild is None:
                return
            member = interaction.user
            if not isinstance(member, discord.Member) or (not member.guild_permissions.administrator and member.id != interaction.guild.owner_id):
                return await interaction.response.send_message(
                    "Administrateur uniquement. / Administrators only.", ephemeral=True
                )
            await set_language(self.bot, interaction.guild.id, language)
            if language == LANG_EN:
                e = embeds.success("English is now the server language. Command names in `+help` and the setup interface are displayed in English.", title="🇬🇧 Language selected")
            else:
                e = embeds.success("Le francais est maintenant la langue du serveur. Les noms dans `+help` et l'interface de configuration sont affiches en francais.", title="🇫🇷 Langue selectionnee")
            await interaction.response.edit_message(embed=e, view=None)

        async def fr_callback(interaction: discord.Interaction): await choose(interaction, LANG_FR)
        async def en_callback(interaction: discord.Interaction): await choose(interaction, LANG_EN)
        fr.callback = fr_callback; en.callback = en_callback
        self.add_item(fr); self.add_item(en)


async def _find_prompt_channel(guild: discord.Guild) -> discord.TextChannel | None:
    candidates: Iterable[discord.TextChannel] = []
    if guild.system_channel:
        candidates = [guild.system_channel, *guild.text_channels]
    else:
        candidates = guild.text_channels
    seen = set()
    for channel in candidates:
        if channel.id in seen:
            continue
        seen.add(channel.id)
        me = guild.me
        if me is None:
            continue
        perms = channel.permissions_for(me)
        if perms.view_channel and perms.send_messages and perms.embed_links:
            return channel
    return None


async def _send_initial_language_prompt(bot: commands.Bot, guild: discord.Guild) -> None:
    await _ensure_table(bot)
    row = await bot.db.fetchone("SELECT language FROM guild_language_settings WHERE guild_id = ?", (guild.id,))
    if row:
        return
    channel = await _find_prompt_channel(guild)
    if channel is None:
        logger.warning("Aucun salon disponible pour demander la langue sur %s.", guild.id)
        return
    e = embeds.brand(
        '🌐 Choose your language • Choisissez votre langue',
        "**Francais** → les noms des commandes et les interfaces principales seront en francais.\n"
        "**English** → command names and the main interfaces will be in English.\n\n"
        "Ce choix est modifiable plus tard dans `+setup`. / You can change it later in `+setup`.",
    )
    await channel.send(embed=e, view=LanguageChoiceView(bot), allowed_mentions=discord.AllowedMentions.none())


async def _mention_help(bot: commands.Bot, message: discord.Message) -> None:
    if message.author.bot or bot.user is None:
        return
    content = str(message.content or "").strip()
    if content not in {f"<@{bot.user.id}>", f"<@!{bot.user.id}>"}:
        return
    key = int(message.author.id)
    now = time.monotonic()
    stamps = getattr(bot, "_sentrix_language_mention_stamps", {})
    if now - stamps.get(key, 0.0) < 5.0:
        return
    stamps[key] = now
    bot._sentrix_language_mention_stamps = stamps
    language = await get_language(bot, message.guild.id if message.guild else None)
    prefix = "+"
    if message.guild:
        conf = await bot.db.get_guild_config(message.guild.id)
        if conf and conf["prefix"]:
            prefix = conf["prefix"]
    help_name = "help" if language == LANG_EN else "aide"
    setup_name = "setup" if language == LANG_EN else "configurer"
    if language == LANG_EN:
        title = "👋 Need help?"
        text = f"My prefix here is **`{prefix}`**. Use **`{prefix}{help_name}`** for commands or **`{prefix}{setup_name}`** for server setup."
    else:
        title = "👋 Besoin d'aide ?"
        text = f"Mon prefixe ici est **`{prefix}`**. Utilise **`{prefix}{help_name}`** pour les commandes ou **`{prefix}{setup_name}`** pour configurer le serveur."
    try:
        await message.channel.send(embed=embeds.neutral(title, text), allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.HTTPException):
        pass


def _install_listeners(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_language_listeners", False):
        return

    async def guild_join(guild: discord.Guild):
        try:
            await _send_initial_language_prompt(bot, guild)
        except Exception:
            logger.exception("Impossible d'envoyer le choix de langue sur %s.", guild.id)

    async def ready():
        try:
            await _ensure_table(bot)
            for guild in bot.guilds:
                await get_language(bot, guild.id)
        except Exception:
            logger.exception("Prechargement des langues impossible.")

    async def message_listener(message: discord.Message):
        await _mention_help(bot, message)

    bot.add_listener(guild_join, "on_guild_join")
    bot.add_listener(ready, "on_ready")
    bot.add_listener(message_listener, "on_message")
    try:
        bot.add_view(LanguageChoiceView(bot))
    except Exception:
        logger.debug("Vue langue persistante deja enregistree ou indisponible.", exc_info=True)
    bot._sentrix_language_listeners = True


async def install(bot: commands.Bot) -> None:
    """Installation idempotente, rappelee apres chaque extension chargee."""
    await _ensure_table(bot)
    _install_listeners(bot)
    added = install_language_aliases(bot)
    _install_help_patch(bot)
    _install_setup_patch(bot)
    if added:
        logger.info("%s alias linguistiques lies aux commandes existantes (aucun doublon d'objet commande).", added)
