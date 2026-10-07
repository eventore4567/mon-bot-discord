"""Canonical SentriX slash-command surface.

Slash command names are intentionally English, short and predictable.
Prefix commands keep their historical names and callbacks unchanged.
"""
from __future__ import annotations

import logging
import os

from discord.ext import commands

import sentrix_v95_runtime as v95
import sentrix_v98_slash as v98

logger = logging.getLogger("bot.canonical-command-surface")
_INSTALLED = False

ROOTS = {
    "ai": "ai", "info": "info", "utility": "utility", "economy": "economy",
    "level": "levels", "levels": "levels", "game": "games", "games": "games",
    "music": "music", "events": "events", "ticket": "tickets",
    "sanctions": "moderation", "moderation": "moderation", "security": "security",
    "config": "config", "server": "server", "role": "roles", "roles": "roles",
    "embeds": "embeds", "owner": "owner", "more": "utility",
    "giveaway": "giveaway", "invites": "invites", "notifications": "notifications",
    "social": "social", "stats": "stats",
}
ROOT_BACK = {
    "tickets": "ticket", "moderation": "moderation", "security": "security",
    "config": "config", "economy": "economy", "levels": "level",
    "games": "game", "roles": "role", "server": "server", "music": "music",
}
ROOT_DESCRIPTIONS = {
    "ai": "AI assistant, images and intelligent tools.",
    "info": "Information about members, channels, the server and the bot.",
    "utility": "Everyday utilities and practical commands.",
    "economy": "Balance, bank, shop and rewards.",
    "levels": "Levels, XP, reputation and leaderboards.",
    "games": "Mini-games and community activities.",
    "music": "Audio playback, queue and playlists.",
    "events": "Events, tournaments and activities.",
    "tickets": "Tickets, support and ticket settings.",
    "moderation": "Sanctions and moderation tools.",
    "security": "AutoMod, anti-raid, anti-nuke and security.",
    "config": "General SentriX configuration.",
    "server": "Server structure and administration.",
    "roles": "Roles, panels and verification.",
    "embeds": "Embeds, announcements and message design.",
    "owner": "Commands reserved for the SentriX owner.",
    "giveaway": "Giveaways and draws.",
    "invites": "Invites, leaderboards and bonuses.",
    "notifications": "Social notifications and welcome messages.",
    "social": "SentriX social features.",
    "stats": "Statistics and diagnostics.",
    "pro": "SentriX Pro tools.",
    "infinite": "Infinite-mode tools.",
}

# Public English aliases. Internal command names stay untouched.
# Alias généraux. Les alias musique ont leur propre table pour éviter qu'un nom comme
# ``clear`` change aussi la commande de modération.
LEAVES = {
    "membercount": "members",
    "emoji-list": "emojis",
    "reminder-list": "reminders",
    "reminder-cancel": "cancel-reminder",
    "report-bug": "bug-report",
    "bot-status": "status",
    "server-growth": "growth",
    "clearwarnings": "clear-warnings",
    "modhistory": "history",
    "ticket-reopen": "reopen",
    "tickettranscript": "transcript",
    "security-check": "check",
    "security-level": "level",
    "permission-audit": "permissions",
    "server-backup": "backup",
    "server-restore": "restore",
    "lockdown-server": "lockdown",
    "unlock-server": "unlock",
    "blacklist-users": "blocked-users",
    "blacklist-list": "blacklist",
    "blacklist-add": "block",
    "blacklist-remove": "unblock",
    "whitelist-domain": "allow-domain",
    "unwhitelist-domain": "remove-domain",
    "setprefix": "prefix",
    "setmodrole": "mod-role",
    "config-view": "view",
    "config-reset": "reset",
    "create-server": "create",
    "delete-channel": "delete-channel",
    "disablecommand": "disable-command",
    "enablecommand": "enable-command",
    "ignorechannel": "ignore-channel",
    "unignorechannel": "unignore-channel",
    "setwarnrole": "warn-role",
    "setwarnbanthreshold": "warn-threshold",
    "set-xp": "set-xp",
    "add-xp": "add-xp",
    "reset-levels": "reset-levels",
    "levelcheck": "check-level",
    "levelrepair": "repair-level",
    "reactionrole-add": "reaction-add",
    "reactionrole-remove": "reaction-remove",
    "reactionrole-list": "reaction-list",
    "economyleaderboard": "leaderboard",
    "leaderboard-levels": "leaderboard",
    "set-level-role": "level-role",
    "remove-level-role": "remove-level-role",
    "voice-time": "voice-time",
    "ticket": "open",
    "ticketsetup": "setup",
    "ticketpanel": "panel",
    "ticketpanel-toggle": "panel-toggle",
    "tickettype": "type",
    "ticketform": "form",
    "ticketconfig": "settings",
    "ticketlogs": "logs",
    "ticketlimit": "limit",
    "ticketautoclose": "auto-close",
    "giveaway-list": "list",
    "giveaway-create": "create",
    "giveaway-end": "end",
    "giveaway-reroll": "reroll",
    "giveaway-cancel": "cancel",
    "event-join": "join",
    "event-leave": "leave",
    "event-list": "list",
    "event-create": "create",
    "event-cancel": "cancel",
    "tournament-join": "tournament-join",
    "tournament-list": "tournaments",
    "tournament-create": "tournament-create",
    "tournament-start": "tournament-start",
    "invite-leaderboard": "leaderboard",
    "invited-by": "invited-by",
    "addbonusinvites": "bonus-add",
    "removebonusinvites": "bonus-remove",
    "invitebonushistory": "bonus-history",
    "notifs-ping": "add",
    "notifs-list": "list",
    "notifs-remove": "remove",
    "welcome-config": "welcome",
    "guess-number": "guess",
    "math-quiz": "math-quiz",
    "emoji-race": "emoji-race",
    "gamehistory": "history",
    "gameprofile": "profile",
    "gamestats": "stats",
    "gametop": "leaderboard",
    "dailygames": "daily",
    "banque": "bank",
    "collec": "collection",
    "info serveur": "server",
    "info role": "role",
}
MUSIC_LEAVES = {
    "join": "join", "leave": "leave", "play": "play", "pause": "pause",
    "resume": "resume", "skip": "skip", "previous": "previous",
    "stop": "stop", "queue": "queue", "nowplaying": "now-playing",
    "volume": "volume", "loop": "loop", "shuffle": "shuffle",
    "remove": "remove", "clear": "clear", "seek": "seek",
    "autoplay": "autoplay",
}
PLAYLIST_LEAVES = {
    "create": "create", "import": "import", "add": "add",
    "list": "list", "show": "show", "play": "play", "remove": "remove",
    "clear": "clear", "rename": "rename", "delete": "delete",
}
DUPLICATES = frozenset({
    "leaderboard-money", "me", "rank", "buyrole", "ask", "chat", "chat-reset",
    "embed-create", "latency", "levelroles",
})
BUCKETS = {
    ("ticket", "panel"): "panels", ("ticket", "config"): "config",
    ("ticket", "manage"): "manage", ("ticket", "stats"): "history",
    ("moderation", "members"): "members", ("moderation", "cases"): "cases",
    ("moderation", "emoji"): "emojis", ("moderation", "general"): "general",
    ("security", "lists"): "lists", ("security", "backup"): "backup",
    ("security", "general"): "general", ("config", "commands"): "commands",
    ("config", "general"): "general", ("utility", "general"): "general",
    ("config", "channels"): "channels", ("config", "levels"): "levels",
    ("economy", "wallet"): "wallet", ("economy", "rewards"): "rewards",
    ("economy", "shop"): "shop", ("economy", "ranking"): "ranking",
    ("economy", "admin"): "admin", ("economy", "general"): "general",
    ("level", "profile"): "profile", ("level", "ranking"): "ranking",
    ("level", "general"): "general", ("game", "quick"): "quick",
    ("game", "races"): "races", ("game", "adventure"): "adventure",
    ("game", "general"): "general", ("role", "manage"): "manage",
    ("role", "panels"): "panels", ("role", "reactions"): "reactions",
    ("role", "general"): "general", ("server", "build"): "build",
    ("server", "channels"): "channels", ("server", "backup"): "backup",
    ("server", "manage"): "manage", ("server", "general"): "general",
}


# ---------------------------------------------------------------------------
# Legacy short-slash toggle
# ---------------------------------------------------------------------------
# Noms slash courts (validés le 20/09/2026). Désactivés par défaut : les commandes
# slash sont GLOBALES à l'application Discord, donc partagées entre le service primaire
# et le standby. Activer SENTRIX_SHORT_SLASH_NAMES=1 sur les DEUX services en même temps
# (au déploiement sur main), jamais sur un seul, sinon l'autre instance ne reconnaît
# plus les noms synchronisés.
# ---------------------------------------------------------------------------
SHORT_SLASH_ENV = "SENTRIX_SHORT_SLASH_NAMES"


def short_slash_enabled() -> bool:
    return (os.getenv(SHORT_SLASH_ENV) or "0").strip().casefold() in {"1", "true", "yes", "on"}


SHORT_ROOTS: dict[str, str] = {}
SHORT_TARGETS: dict[str, tuple[str, str, str]] = {}
SHORT_DUPLICATES = frozenset()
SHORT_DIRECT: dict[str, str] = {}


_ENGLISH_NAME_TOKENS = {
    "aide": "help", "ia": "ai", "infos": "info", "outils": "tools",
    "pratiques": "utility", "economie": "economy", "niveaux": "levels",
    "niveau": "level", "jeux": "games", "musique": "music",
    "evenements": "events", "serveur": "server", "salon": "channel",
    "salons": "channels", "securite": "security", "reglages": "settings",
    "utilisateur": "user", "utilisateurs": "users", "membre": "member",
    "membres": "members", "profil": "profile", "historique": "history",
    "etat": "status", "statut": "status", "quarantaine": "quarantine",
    "preuve": "proof", "panneau": "panel", "panneaux": "panels",
    "liste": "list", "ajouter": "add", "retirer": "remove",
    "supprimer": "delete", "creer": "create", "modifier": "edit",
    "envoyer": "send", "apercu": "preview", "renommer": "rename",
    "sauvegarder": "save", "charger": "load", "recherche": "search",
    "modele": "model", "classement": "leaderboard", "portefeuille": "wallet",
    "recompenses": "rewards", "boutique": "shop", "administration": "admin",
    "rapides": "quick", "courses": "races", "aventure": "adventure",
    "gestion": "manage", "creation": "build", "sauvegarde": "backup",
    "divers": "general", "proprietaire": "owner", "invitations": "invites",
    "statistiques": "stats", "ouvrir": "open", "fermer": "close",
    "annuler": "cancel", "terminer": "end", "relancer": "reroll",
    "rejoindre": "join", "quitter": "leave", "bienvenue": "welcome",
    "solde": "balance", "quotidien": "daily", "hebdo": "weekly",
    "travailler": "work", "payer": "pay", "inventaire": "inventory",
    "banque": "bank", "avertir": "warn", "avertissements": "warnings",
    "nettoyer": "clear", "verrouiller": "lock", "deverrouiller": "unlock",
    "pseudo": "nickname", "debannir": "unban", "expulser": "kick",
    "traduire": "translate", "croissance": "growth",
}


def _english_public_name(value: object) -> str:
    """Normalize any legacy French token before a slash name reaches Discord."""
    safe = v95._safe_name(value)
    parts = [_ENGLISH_NAME_TOKENS.get(part, part) for part in safe.split("-")]
    return v95._safe_name("-".join(parts))


def _install_flat_bucket_support() -> None:
    """Sous-groupe "" = feuille directement sous la racine, même pour une racine
    sémantique (/securite antinuke au lieu de /securite antinuke antinuke)."""
    if getattr(v98, "_sentrix_flat_bucket", False):
        return
    original = v98._add_semantic_root

    def add_semantic_root(bot, root, members, report):
        flat = [target for target in members if v98.semantic_bucket(root.name, target) == ""]
        grouped = [target for target in members if target not in flat]
        if grouped:
            original(bot, root, grouped, report)
        used = {child.name for child in root.commands}
        for target in flat:
            leaf = v95._unique_leaf(target.leaf_name, used, target.original_name)
            callback, native = v95._make_callback(bot, target.command)
            import discord.app_commands as app_commands
            slash = app_commands.Command(name=leaf, description=v95._description(target.command), callback=callback)
            root.add_command(slash)
            report[f"/{root.name} {slash.name}"] = {
                "original": target.original_name, "category": root.name,
                "subcategory": None, "native_options": bool(native),
            }
        if len(root.commands) > v95.MAX_CHILDREN:
            raise RuntimeError(f"V98 group too large: {root.name} has {len(root.commands)} children")

    v98._add_semantic_root = add_semantic_root
    v98._sentrix_flat_bucket = True


def _qualified(command: commands.Command) -> str:
    return str(getattr(command, "qualified_name", "") or getattr(command, "name", "")).casefold().strip()


def _simple(command: commands.Command) -> str:
    return str(getattr(command, "name", "") or "").casefold().strip()


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    old_should_expose = v95._should_expose
    old_group_for = v95._group_for
    old_bucket = v98.semantic_bucket
    old_surface = v95._add_grouped_surface

    short = short_slash_enabled()

    def should_expose(command: commands.Command) -> bool:
        name, simple = _qualified(command), _simple(command)
        if getattr(command, "hidden", False) or name in DUPLICATES or simple in DUPLICATES:
            return False
        # Les groupes servent de conteneurs et ne doivent jamais devenir des
        # fausses feuilles (/music lecture music, /music lecture playlist).
        # +play reste l'alias préfixé historique ; son slash est fourni une seule
        # fois par /music jouer via "music play".
        if name in {"music", "music playlist", "play"}:
            return False
        if short and (name in SHORT_DUPLICATES or simple in SHORT_DUPLICATES):
            return False
        return bool(old_should_expose(command))

    def group_for(command: commands.Command):
        qualified, simple = _qualified(command), _simple(command)
        if short and qualified in SHORT_TARGETS:
            target_root, _bucket, target_leaf = SHORT_TARGETS[qualified]
            return target_root, target_leaf
        if qualified.startswith("sentrixpro "):
            pro_leaf = {
                "quarantine-setup": "quarantine",
                "ticket-summary": "ticket-summary",
            }.get(simple, simple)
            return "pro", pro_leaf
        if qualified.startswith("infinit "):
            return "infinite", simple
        if qualified.startswith("music playlist "):
            return "music", PLAYLIST_LEAVES.get(simple, simple)
        if qualified.startswith("music "):
            return "music", MUSIC_LEAVES.get(simple, simple)
        root, leaf = old_group_for(command)
        root = ROOTS.get(str(root).casefold(), str(root).casefold())
        if short:
            root = SHORT_ROOTS.get(root, root)
        return root, _english_public_name(LEAVES.get(qualified, LEAVES.get(simple, leaf)))

    def bucket(root_name: str, target: v95.SlashTarget) -> str:
        root = str(root_name).casefold()
        original_root = ROOT_BACK.get(root, root)
        original_name = str(target.original_name or "").casefold().strip()
        simple = original_name.split(" ")[-1]
        if short and original_name in SHORT_TARGETS:
            return SHORT_TARGETS[original_name][1]
        if root == "music" or original_root == "music":
            if original_name.startswith("music playlist "):
                return "playlist"
            if simple in {"queue", "remove", "clear"}:
                return "queue"
            # Jouer/pause/reprendre/suivant/arrêter/en-cours/volume/boucle/
            # mélanger/rejoindre/quitter/position/lecture-auto restent directement
            # sous /music : pas de sous-groupe "lecture" artificiel.
            return ""
        original_bucket = old_bucket(original_root, target)
        return BUCKETS.get((original_root, original_bucket), original_bucket)

    def leaf(_root: str, _bucket: str, target: v95.SlashTarget) -> str:
        root = str(_root).casefold()
        original_name = str(target.original_name or "").casefold().strip()
        simple = original_name.split(" ")[-1]

        # _build_targets() rendait les feuilles uniques à l'échelle de toute la
        # racine avant de connaître les sous-groupes. Ainsi "music remove" et
        # "music playlist remove" pouvaient produire retirer-2 alors qu'ils vivent
        # dans deux sous-groupes différents. Recalcule ici le vrai nom public
        # depuis la commande métier : l'unicité est ensuite gérée dans chaque
        # sous-groupe par V98.
        if root == "music":
            if original_name.startswith("music playlist "):
                return _english_public_name(PLAYLIST_LEAVES.get(simple, simple))
            if original_name.startswith("music "):
                return _english_public_name(MUSIC_LEAVES.get(simple, simple))

        return _english_public_name(target.leaf_name)

    def chunks(bucket_name: str, count: int) -> list[str]:
        base = v95._safe_name(bucket_name)
        if count <= 1:
            return [base]
        return [base] + [
            v95._safe_name("more" if index == 2 else f"more-{index}")
            for index in range(2, count + 1)
        ]

    def surface(bot: commands.Bot):
        for duplicate in DUPLICATES:
            command = bot.get_command(duplicate)
            if command is not None:
                command.hidden = True
        return old_surface(bot)

    v95._should_expose = should_expose
    v95._group_for = group_for
    v95._add_grouped_surface = surface
    v98.semantic_bucket = bucket
    # La surface canonique utilise des feuilles directement sous /music et
    # d'autres racines sémantiques même lorsque le mode "short" est désactivé.
    _install_flat_bucket_support()
    if short:
        try:
            import sentrix_command_surface_v110 as v110
            v110.STANDARD_DIRECT_SLASH.update(SHORT_DIRECT)
        except Exception:
            logger.warning("Racines directes courtes non appliquées (V110 indisponible).", exc_info=True)
    v98.semantic_leaf = leaf
    v98._chunk_group_names = chunks
    v98.FORCED_SEMANTIC_ROOTS = frozenset({
        "tickets", "moderation", "security", "config", "economy",
        "levels", "games", "roles", "server", "music",
    })
    v95.GROUP_DESCRIPTIONS.update(ROOT_DESCRIPTIONS)
    v98.SUBGROUP_DESCRIPTIONS.update({
        ("music", "queue"): "View and manage the music queue.",
        ("music", "playlist"): "Create, import and play your playlists.",
    })
    logger.info("Canonical slash surface active: English names, compact groups, /music structured.")


__all__ = ["install", "ROOTS", "LEAVES", "MUSIC_LEAVES", "PLAYLIST_LEAVES", "SHORT_TARGETS", "SHORT_ROOTS", "SHORT_DIRECT", "short_slash_enabled"]
