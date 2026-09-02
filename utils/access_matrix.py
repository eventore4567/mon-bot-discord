"""SentriX — source de vérité UNIQUE des permissions de commandes.

Ce module est le seul endroit du dépôt qui décide si une personne peut exécuter
une commande. ``+commande`` et ``/commande`` appellent tous les deux
``evaluate()`` : par construction, ils ne peuvent pas diverger.

ORDRE DE PRIORITÉ (identique pour les deux transports)
------------------------------------------------------
 1. blacklist globale SentriX
 2. commande owner-only globale        -> seul l'owner global passe
 3. owner global SentriX               -> passe partout ailleurs
 4. module désactivé sur le serveur    -> refus, même pour l'owner du serveur
 5. setup pour owner serveur           -> accès de récupération garanti
 6. deny explicite Setup               -> refus
 7. allow explicite Setup              -> accès, sans exiger Administrateur
 8. owner du serveur Discord           -> accès aux fonctions de SON serveur
 9. Administrateur Discord             -> accès serveur, jamais owner global
10. permission Discord requise / rôle staff configuré
11. commande publique
12. fail-closed                        -> Administrateur requis

Pourquoi le deny explicite passe AVANT le bypass owner du serveur : sinon un
propriétaire ne peut pas se retirer volontairement une commande dangereuse.
``setup`` est l'exception de récupération : le propriétaire du serveur y garde
toujours accès afin de pouvoir réparer ses propres règles.

Pourquoi le module désactivé (4) passe avant tout sauf l'owner global : couper
un module doit couper le module, sans quoi « désactivé » ne veut rien dire.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("bot.access-matrix")

# ---------------------------------------------------------------------------
# 1. NIVEAUX D'ACCÈS
# ---------------------------------------------------------------------------

PUBLIC_COMMANDS = frozenset({
    # Aide et utilitaires
    "help", "ping", "avatar", "info", "userinfo", "status", "about", "profile-card",
    "channelinfo", "membercount", "emoji-list", "poll", "remind",
    "reminder-list", "reminder-cancel", "translate", "weather", "suggest",
    "report-bug", "afk", "roll", "choose", "privacy-policy",
    # Preuve
    "proof", "proofstatus",
    # IA (soumises aux sous-interrupteurs IA du serveur)
    "sentrix", "ask", "chat-reset", "summarize", "image-prompt", "image",
    "explain", "rewrite", "fact-check", "ai", "chat", "improve", "correct",
    "ai-translate", "code",
    # Économie et niveaux
    "balance", "economy", "daily", "weekly", "work", "rob", "pay",
    "economyleaderboard", "leaderboard-money", "shop", "buy", "buyrole",
    "inventory", "sell", "gamble", "deposit", "withdraw", "banque",
    "stats", "me", "level", "rank", "leaderboard-levels", "level-roles",
    "profile", "set-bio", "rep", "reputation", "repleaderboard", "voice-time",
    # Tickets, événements, invitations
    "ticket", "ticketcenter", "giveaway-list", "event-join", "event-leave",
    "event-list", "tournament-join", "tournament-list", "invites",
    "invite-leaderboard", "invited-by",
    # Statistiques publiques
    "bot-status", "server-growth", "command-stats", "latency", "changelog",
    "feedback", "botinfo",
    # Mini-jeux
    "rps", "guess-number", "trivia", "tictactoe", "hangman", "math-quiz",
    "blackjack", "slots", "coinflip", "dice", "luckyroll", "highlow", "memory",
    "reaction", "scramble", "wordgame", "emojiquiz", "colorquiz", "fasttype",
    "duel", "connect4", "numberduel", "reactionduel", "quizduel", "triviastart",
    "wordrace", "reactionevent", "guessrace", "mathrace", "lastmessage",
    "emoji-race", "adventure", "dungeon", "mining", "fishing", "treasure",
    "hunt", "explore", "gamehistory", "gameprofile", "gamestats", "gametop",
    "dailygames", "drop", "season",
    # Musique
    "join", "leave", "play", "pause", "resume", "skip", "stop", "queue",
    "nowplaying", "volume", "loop", "shuffle", "remove-from-queue",
    "clear-queue", "playlist-save", "playlist-load",
    # Hubs et profils membre (anciennement fail-closed par oubli)
    "home", "gamehub", "economyhub", "checkin", "progress", "profilecard",
    "achievements", "challenges", "missions", "gamelobby", "matchmake",
    "market", "market-buy", "market-sell", "market-cancel", "market-find",
    "market-history", "market-my", "transactions", "shopwindow",
    "sentrix-plus", "sentrixpro",
    # Salons vocaux temporaires : le membre pilote SON salon
    "voice-limit", "voice-lock", "voice-name", "voice-transfer", "voice-unlock",
    # Commandes membre qui tombaient en fail-closed faute d'etre declarees ici :
    # elles n'ont aucun check local et affichent seulement des informations.
    "leaderboard", "serverinfo", "gameseason",
})

OWNER_ONLY_COMMANDS = frozenset({
    "bl", "blinfo", "unbl", "editbl", "sync", "syncguild", "setstatus",
    "status-rotate", "footer", "theme", "set-bot", "bot-servers", "bot-leave",
    # Diagnostics globaux (checks.is_bot_owner dans les cogs d'origine)
    "logs-diag", "reset-logs-all",
})

# ---------------------------------------------------------------- NIVEAU 4
# Propriétaire du SERVEUR uniquement. Un administrateur Discord ne suffit pas.
#
# Critère unique et volontairement etroit : destruction irreversible de donnees ou de
# structure, touchant tout le serveur. Les outils d'URGENCE (panic, lockdown-server,
# antinuke, smartlockdown) restent volontairement au niveau administrateur : pendant un
# raid, le staff doit pouvoir reagir sans attendre le proprietaire.
GUILD_OWNER_COMMANDS = frozenset({
    # Structure du serveur
    "wipe-server",          # supprime tous les salons et tous les roles
    "create-server",        # reconstruit entierement le serveur
    "create",               # racine du constructeur (+create server / sentrix / manox)
    "server-restore",       # ecrase le serveur vivant avec une sauvegarde
    # Donnees de tous les membres
    "config-reset",         # efface toute la configuration SentriX
    "reset-economy",        # remet a zero les soldes de TOUS les membres
    "reset-levels",         # remet a zero l'XP de TOUS les membres
    "represet",             # remet a zero la reputation de TOUS les membres
    "proofreset",           # efface toutes les preuves de verification
    # Diffusion privee a l'ensemble du serveur
    "dmall",                # envoie un MP a tous les membres non-bot
})

CUSTOM_PERMISSION_COMMANDS = frozenset({"embed"})

# Sous-commandes dont le niveau DIFFERE de leur groupe. Sans cette table, le garde
# evalue la racine et une sous-commande ne peut jamais etre plus stricte que son
# groupe : c'est ce qui rendait "+season start" accessible a tout membre alors que la
# racine "season" est publique.
SUBCOMMAND_TIERS: dict[str, str] = {
    # Groupe public, sous-commandes administratives
    "season start": "economie",
    "season end": "economie",
    "sentrixpro aimod": "configuration",
    "sentrixpro autorole": "configuration",
    "sentrixpro digest": "configuration",
    "sentrixpro goal": "configuration",
    "sentrixpro history": "configuration",
    "sentrixpro live": "configuration",
    "sentrixpro lockdown": "securite",
    "sentrixpro module": "configuration",
    "sentrixpro modules": "configuration",
    "sentrixpro notifications": "configuration",
    "sentrixpro quarantine-setup": "securite",
    "sentrixpro security": "securite",
    "sentrixpro ticket-summary": "tickets",
    "sentrixpro welcome": "configuration",
}

DISCORD_PERMISSION_COMMANDS: dict[str, str] = {
    "ban": "ban_members",
    "tempban": "ban_members",
    "unban": "ban_members",
    "kick": "kick_members",
    "mute": "moderate_members",
    "unmute": "moderate_members",
    "warn": "moderate_members",
    "unwarn": "moderate_members",
    "warnings": "moderate_members",
    "clearwarnings": "moderate_members",
    "case": "moderate_members",
    "casefull": "moderate_members",
    "caseproof": "moderate_members",
    "modhistory": "moderate_members",
    "modundo": "moderate_members",
    "modcenter": "moderate_members",
    "userhistory": "moderate_members",
    "staffnote": "moderate_members",
    "suspiciouslist": "moderate_members",
    "quarantine": "moderate_members",
    "unquarantine": "moderate_members",
    "clear": "manage_messages",
    "say": "manage_messages",
    "embed-create": "manage_messages",
    "schedule-send": "manage_messages",
    "schedule-list": "manage_messages",
    "schedule-cancel": "manage_messages",
    "sticky-set": "manage_messages",
    "sticky-every": "manage_messages",
    "sticky-off": "manage_messages",
    "slowmode": "manage_channels",
    "lock": "manage_channels",
    "unlock": "manage_channels",
    "hide": "manage_channels",
    "show": "manage_channels",
    "smartlockdown": "manage_channels",
    "ticket-reopen": "manage_channels",
    "reopenticket": "manage_channels",
    "tickettranscript": "manage_channels",
    "ticketstats": "manage_channels",
    "ticketstaffstats": "manage_channels",
    "nickname": "manage_nicknames",
    "nick": "manage_nicknames",
    "resetnick": "manage_nicknames",
    "move": "move_members",
    "disconnect": "move_members",
    "role-snapshot": "manage_roles",
    "role-restore": "manage_roles",
    "giverole": "manage_roles",
    "removerole": "manage_roles",
    "protectmember": "manage_roles",
    "addemoji": "manage_emojis_and_stickers",
    "deleteemoji": "manage_emojis_and_stickers",
    "server-health": "manage_guild",
    "systemstatus": "manage_guild",
    "starboard-setup": "manage_guild",
    "starboard-off": "manage_guild",
    "voicehub-setup": "manage_guild",
    "voicehub-off": "manage_guild",
}

CATEGORY_COMMANDS: dict[str, frozenset[str]] = {
    "configuration": frozenset({
        # Classees explicitement : elles tombaient en fail-closed, donc admin
        # par accident plutot que par declaration.
        "server-managed", "verification-review", "verification-calibration",
        "setprefix", "setmodrole", "setlogchannel", "create-logs", "logs-status",
        "logsetup", "logs", "setwelcomechannel", "setgoodbyechannel",
        "setwelcomemessage", "setgoodbyemessage", "setticketlogchannel",
        "setautorole", "createrole", "setwarnrole", "setwarnbanthreshold",
        "disablecommand", "enablecommand", "ignorechannel", "unignorechannel",
        "setlevelchannel", "setsuggestchannel", "setannouncechannel",
        "setgiveawaychannel", "config-view", "config-reset", "setup",
        "create-server", "delete-channel", "verify-setup", "verify-panel",
        "rolepanel", "rolepanel-refresh", "reactionrole-add",
        "reactionrole-remove", "reactionrole-list", "set-level-role",
        "remove-level-role", "set-xp", "add-xp", "reset-levels", "levelcheck",
        "levelrepair", "repconfig", "repadd", "repremove", "represet",
        "rephistory", "statsconfig", "levelroles", "addbonusinvites",
        "removebonusinvites", "invitebonushistory", "designsetup",
        "design-theme", "iconsetup", "embedconfig", "giveaway", "giveaway-create",
        "giveaway-end", "giveaway-reroll", "giveaway-cancel",
        "giveaway-blacklist", "giveaway-unblacklist", "event-create",
        "event-cancel", "tournament-create", "tournament-start", "announce",
        "notifs-ping", "notifs-list", "notifs-remove", "welcome-config",
        "set-nickname", "alias", "diagnostic",
        # Anciennement fail-closed par oubli
        "suivi-bot", "setup-auto", "server-audit", "health", "healthcheck",
        "create", "level-system", "security-repair",
        # Vérification par preuve (administration)
        "proofsetup", "proofexample", "proofexample-remove", "proofexamples",
        "proofpanel", "proofreset",
    }),
    "tickets": frozenset({
        "ticketsetup", "ticketpanel", "ticketpanel-toggle", "tickettype",
        "ticketform", "ticketconfig", "ticketlogs", "ticketlimit",
        "ticketautoclose", "ticketreopenwindow",
    }),
    "moderation": frozenset({"sanctiondm", "sanctionpolicy"}),
    "securite": frozenset({
        # Classees explicitement : elles tombaient en fail-closed, donc admin
        # par accident plutot que par declaration.
        "whitelist", "unwhitelist",
        "antispam", "antilink", "antiinvite", "antimention", "anticaps",
        "antiemoji", "antiraid", "antibot", "antiaccount", "antiscam",
        "antinuke", "antinuke-whitelist-add", "antinuke-whitelist-remove",
        "antinuke-whitelist-list", "lockdown-server", "unlock-server",
        "automod-status", "security-check", "automod-escalation",
        "automod-exempt-role-add", "automod-exempt-role-remove",
        "automod-history", "security-level", "blacklist-add",
        "blacklist-remove", "blacklist-list", "blacklist-user",
        "unblacklist-user", "blacklist-users", "panic", "whitelist-domain",
        "unwhitelist-domain", "permission-audit", "server-backup",
        "server-restore", "syncbl", "unsyncbl",
        # Anciennement fail-closed par oubli
        "security", "antigif", "antinuke-config", "backup-now", "incidents",
        "nukewhitelist", "serversnapshot",
    }),
    "economie": frozenset({
        "shopsetup", "shoppanel", "shoprole", "give-money", "reset-economy",
        "gamesetup", "economy-system", "economy-audit", "shoppromo",
        "shopstock", "shopwindowclear",
    }),
    "ai": frozenset({
        "aisetup", "aidiag", "aicenter", "aicontext", "aimemorychannel",
        "airolequota",
    }),
    "logs": frozenset({"createalllogs", "testlogs", "logevent", "logsearch"}),
    "complete": frozenset({"wipe-server", "roleall", "massrole"}),
}

PERMISSION_LABELS = {
    "administrator": "Administrateur",
    "manage_guild": "Gérer le serveur",
    "manage_channels": "Gérer les salons",
    "manage_roles": "Gérer les rôles",
    "manage_messages": "Gérer les messages",
    "manage_nicknames": "Gérer les pseudos",
    "moderate_members": "Exclure temporairement des membres",
    "kick_members": "Expulser des membres",
    "ban_members": "Bannir des membres",
    "move_members": "Déplacer des membres",
    "manage_emojis_and_stickers": "Gérer les émojis et autocollants",
    "manage_webhooks": "Gérer les webhooks",
    "view_audit_log": "Voir les logs d'audit",
}

# Completement de la table : 46 permissions Discord tombaient dans le repli et
# s'affichaient en anglais (« Send messages », « Mention everyone ») dans les
# messages d'erreur, +setup et la fiche d'un role. Les libelles suivent ceux de
# l'interface Discord francaise.
PERMISSION_LABELS.update({
    "add_reactions": "Ajouter des réactions",
    "attach_files": "Joindre des fichiers",
    "bypass_slowmode": "Ignorer le mode lent",
    "change_nickname": "Changer de pseudo",
    "connect": "Se connecter",
    "create_events": "Créer des événements",
    "create_expressions": "Créer des expressions",
    "create_instant_invite": "Créer une invitation",
    "create_polls": "Créer des sondages",
    "create_private_threads": "Créer des fils privés",
    "create_public_threads": "Créer des fils publics",
    "deafen_members": "Rendre des membres sourds",
    "embed_links": "Intégrer des liens",
    "external_emojis": "Utiliser des émojis externes",
    "external_stickers": "Utiliser des autocollants externes",
    "manage_emojis": "Gérer les émojis",
    "manage_events": "Gérer les événements",
    "manage_expressions": "Gérer les expressions",
    "manage_permissions": "Gérer les permissions",
    "manage_threads": "Gérer les fils",
    "mention_everyone": "Mentionner @everyone, @here et tous les rôles",
    "mute_members": "Rendre des membres muets",
    "pin_messages": "Épingler des messages",
    "priority_speaker": "Voix prioritaire",
    "read_message_history": "Lire l'historique des messages",
    "read_messages": "Voir les salons",
    "request_to_speak": "Demander à parler",
    "send_messages": "Envoyer des messages",
    "send_messages_in_threads": "Envoyer des messages dans les fils",
    "send_polls": "Envoyer des sondages",
    "send_tts_messages": "Envoyer des messages vocaux synthétisés",
    "send_voice_messages": "Envoyer des messages vocaux",
    "set_voice_channel_status": "Définir le statut d'un salon vocal",
    "speak": "Parler",
    "stream": "Partager sa vidéo",
    "use_application_commands": "Utiliser les commandes d'application",
    "use_embedded_activities": "Lancer des activités",
    "use_external_apps": "Utiliser des applications externes",
    "use_external_emojis": "Utiliser des émojis externes",
    "use_external_sounds": "Utiliser des sons externes",
    "use_external_stickers": "Utiliser des autocollants externes",
    "use_soundboard": "Utiliser la sonothèque",
    "use_voice_activation": "Utiliser la détection de voix",
    "view_channel": "Voir les salons",
    "view_creator_monetization_analytics": "Voir les statistiques de monétisation",
    "view_guild_insights": "Voir les analyses du serveur",
})

# Permissions qui donnent les cles du serveur. Les signaler sur la fiche d'un role
# evite d'accorder « Gerer les roles » sans mesurer ce que cela ouvre.
PERMISSIONS_SENSIBLES = (
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "manage_webhooks", "ban_members", "kick_members", "moderate_members",
    "manage_messages", "mention_everyone", "manage_expressions", "manage_events",
    "view_audit_log",
)


KNOWN_COMMANDS = (
    PUBLIC_COMMANDS
    | OWNER_ONLY_COMMANDS
    | GUILD_OWNER_COMMANDS
    | CUSTOM_PERMISSION_COMMANDS
    | frozenset(DISCORD_PERMISSION_COMMANDS)
    | frozenset().union(*CATEGORY_COMMANDS.values())
)

# Rattachement commande -> module désactivable dans Setup.
CATEGORY_TO_MODULE = {
    "moderation": "moderation",
    "securite": "security",
    "tickets": "tickets",
    "economie": "economy",
    "ai": "ai",
    "logs": "logs",
}

_MODULE_BY_COMMAND: dict[str, str] = {}
for _cat, _names in CATEGORY_COMMANDS.items():
    _module = CATEGORY_TO_MODULE.get(_cat)
    if _module:
        for _n in _names:
            _MODULE_BY_COMMAND[_n] = _module

# Les commandes à permission Discord appartiennent aussi à un module : sans ce
# rattachement, couper « Modération » ne coupait ni +ban ni +mute.
_MODULE_BY_PERMISSION_COMMAND = {
    "moderation": {
        "ban", "tempban", "unban", "kick", "mute", "unmute", "warn", "unwarn",
        "warnings", "clearwarnings", "case", "casefull", "caseproof",
        "modhistory", "modundo", "modcenter", "userhistory", "staffnote",
        "suspiciouslist", "quarantine", "unquarantine", "clear", "say",
        "slowmode", "lock", "unlock", "hide", "show", "smartlockdown",
        "nickname", "nick", "resetnick", "move", "disconnect",
    },
    "tickets": {
        "ticket-reopen", "reopenticket", "tickettranscript", "ticketstats",
        "ticketstaffstats",
    },
    "roles": {
        "role-snapshot", "role-restore", "giverole", "removerole",
        "protectmember",
    },
}
for _module, _names in _MODULE_BY_PERMISSION_COMMAND.items():
    for _n in _names:
        _MODULE_BY_COMMAND.setdefault(_n, _module)

# Repli historique : le rôle configuré via ``setmodrole`` remplace la permission
# Discord pour les actions courantes UNIQUEMENT. Il n'accorde jamais le
# bannissement ni la gestion du serveur : ces droits passent obligatoirement par
# une permission Discord réelle ou par une règle explicite dans Setup, sans quoi
# « Ban OFF » pour un modérateur serait impossible à exprimer.
STAFF_ROLE_FALLBACK_PERMISSIONS = frozenset({
    "moderate_members", "kick_members", "manage_messages",
    "manage_nicknames", "move_members", "manage_channels",
})

MODULE_LABELS = {
    "moderation": "Modération",
    "security": "Sécurité",
    "logs": "Logs",
    "tickets": "Tickets",
    "welcome": "Bienvenue & départ",
    "roles": "Rôles",
    "levels": "Niveaux",
    "economy": "Économie",
    "notifications": "Notifications",
    "ai": "IA",
}

AI_IMAGE_COMMANDS = frozenset({"image", "image-prompt"})
AI_ALWAYS_ALLOWED = frozenset({"aisetup", "aidiag"})


def normalise(value: Any) -> str:
    """Normalisation UNIQUE. Les deux transports doivent utiliser celle-ci."""
    return str(value or "").strip().casefold().lstrip("+/")


def resolve_name(qualified_name: Any, root_name: Any = None) -> str:
    """Nom a evaluer : le nom COMPLET s'il est connu, sinon la racine.

    Le garde evalue historiquement ``root.name``, ce qui fait heriter alias et
    sous-commandes du niveau de leur groupe. C'est le bon defaut, mais il empeche une
    sous-commande d'etre PLUS stricte que son groupe. Cette resolution corrige ce seul
    cas, sans changer le comportement des centaines de sous-commandes qui doivent bien
    heriter.
    """
    qualified = normalise(qualified_name)
    if qualified and qualified in SUBCOMMAND_TIERS:
        return qualified
    if qualified and qualified in GUILD_OWNER_COMMANDS:
        return qualified
    root = normalise(root_name) if root_name is not None else ""
    if root:
        return root
    return qualified.split(" ")[0] if qualified else ""


def module_for_command(name: str) -> str | None:
    name = normalise(name)
    if name in _MODULE_BY_COMMAND:
        return _MODULE_BY_COMMAND[name]
    if name in PUBLIC_COMMANDS:
        if name in {"balance", "daily", "weekly", "work", "rob", "pay", "shop",
                    "buy", "buyrole", "inventory", "sell", "gamble", "deposit",
                    "withdraw", "banque", "economy", "economyleaderboard",
                    "leaderboard-money", "market", "market-buy", "market-sell",
                    "market-cancel", "market-find", "market-history",
                    "market-my", "transactions", "shopwindow", "economyhub"}:
            return "economy"
        if name in {"stats", "me", "level", "rank", "leaderboard-levels",
                    "level-roles", "profile", "set-bio", "rep", "reputation",
                    "repleaderboard", "voice-time", "progress", "achievements",
                    "profilecard"}:
            return "levels"
        if name in {"sentrix", "ask", "chat", "chat-reset", "summarize",
                    "image", "image-prompt", "explain", "rewrite", "fact-check",
                    "ai", "improve", "correct", "ai-translate", "code"}:
            return "ai"
        if name in {"ticket", "ticketcenter"}:
            return "tickets"
    return None


def permission_label(permission: str) -> str:
    """Libelle francais d'une permission Discord.

    Repli lisible pour une permission absente de la table : « manage_webhooks »
    devient « Manage webhooks » plutot que d'etre affiche en snake_case a un membre.
    """
    connue = PERMISSION_LABELS.get(permission)
    if connue:
        return connue
    brut = str(permission or "").strip()
    if not brut:
        return "une permission"
    return brut.replace("_", " ").capitalize()


def access_tier(name: str) -> str:
    key = normalise(name)
    if key in GUILD_OWNER_COMMANDS:
        return "guild-owner"
    if key in SUBCOMMAND_TIERS:
        return f"categorie:{SUBCOMMAND_TIERS[key]}"
    # Sous-commande sans regle propre : elle herite de son groupe, exactement comme le
    # fait le garde au runtime via resolve_name.
    if " " in key:
        return access_tier(key.split(" ")[0])
    return _access_tier_base(key)


def _access_tier_base(name: str) -> str:
    """Niveau théorique, sans état serveur. Utilisé par +help et /help."""
    name = normalise(name)
    if name in OWNER_ONLY_COMMANDS:
        return "owner-global"
    if name in PUBLIC_COMMANDS:
        return "public"
    if name in CUSTOM_PERMISSION_COMMANDS:
        return "embed-staff"
    if name in DISCORD_PERMISSION_COMMANDS:
        return "discord:" + DISCORD_PERMISSION_COMMANDS[name]
    for category, names in CATEGORY_COMMANDS.items():
        if name in names:
            return "categorie:" + category
    return "fail-closed"


def help_requirement(name: str) -> str:
    """Libellé de permission affiché par +help ET /help. Jamais masqué."""
    tier = access_tier(name)
    if tier == "public":
        return "Tout le monde"
    if tier == "owner-global":
        return "Propriétaire global SentriX"
    if tier == "guild-owner":
        return "Propriétaire du serveur uniquement"
    if tier == "embed-staff":
        return "Gérer les messages / Gérer le serveur / rôle +embed"
    if tier.startswith("discord:"):
        return permission_label(tier.split(":", 1)[1]) + " (ou rôle autorisé dans Setup)"
    if tier.startswith("categorie:"):
        return "Administrateur (ou rôle autorisé dans Setup)"
    return "Administrateur (commande non classée)"


# ---------------------------------------------------------------------------
# 2. DÉCISION
# ---------------------------------------------------------------------------

DENIAL_HEADER = "Vous n'avez pas accès à cette commande."


@dataclass(frozen=True, slots=True)
class AccessDecision:
    allowed: bool
    reason: str = ""
    policy: str = ""

    @property
    def message(self) -> str:
        if self.allowed:
            return ""
        if not self.reason:
            return DENIAL_HEADER
        return f"{DENIAL_HEADER}\n\n{self.reason}"


def _deny(reason: str, policy: str) -> AccessDecision:
    return AccessDecision(False, reason, policy)


def _permissions(author: Any):
    return getattr(author, "guild_permissions", None)


def _is_administrator(author: Any) -> bool:
    perms = _permissions(author)
    return bool(perms is not None and getattr(perms, "administrator", False))


def _has_discord_permission(author: Any, permission: str) -> bool:
    perms = _permissions(author)
    return bool(perms is not None and getattr(perms, permission, False))


def _role_ids(author: Any) -> set[int]:
    out: set[int] = set()
    for role in (getattr(author, "roles", ()) or ()):
        try:
            rid = int(getattr(role, "id", 0) or 0)
        except (TypeError, ValueError):
            continue
        if rid:
            out.add(rid)
    return out


def _is_guild_owner(author: Any, guild: Any) -> bool:
    """Strict : deux identifiants réels et égaux. None == None ne passe pas."""
    author_id = getattr(author, "id", None)
    owner_id = getattr(guild, "owner_id", None)
    if author_id is None or owner_id is None:
        return False
    try:
        return int(author_id) == int(owner_id)
    except (TypeError, ValueError):
        return False


class Backend:
    """Accès base de données. Toutes les méthodes échouent en refus (fail-closed).

    Les instances de bot fournissent leur propre backend via
    ``bot.sentrix_access_backend``. Les tests injectent un backend factice.
    """

    def __init__(self, bot):
        self.bot = bot

    async def is_global_owner(self, user_id: int) -> bool:
        import config
        from database.db import PRIMARY_CREATOR_ID
        if user_id == PRIMARY_CREATOR_ID or user_id in config.OWNER_IDS:
            return True
        try:
            return bool(await self.bot.db.is_bot_creator(user_id))
        except Exception:
            logger.exception("Vérification owner global impossible user=%s", user_id)
            return False

    async def blacklist_reason(self, user_id: int) -> str | None:
        cache = getattr(self.bot, "blacklist_cache", None)
        if not isinstance(cache, dict):
            return None
        reason = cache.get(user_id)
        if reason is None:
            return None
        return str(reason or "Aucune raison fournie")

    async def module_enabled(self, guild_id: int, module: str) -> bool:
        """Meme semantique qu'avant : aucune ligne = module actif.

        La LECTURE passe par le cache de cogs.setup_v2_core, proprietaire canonique de
        module_settings, pour que les trois lecteurs du chemin chaud partagent une seule
        entree de cache et une seule invalidation. L'import est fait ici et non en tete
        de fichier : utils ne doit pas dependre de cogs au chargement.
        """
        try:
            from cogs.setup_v2_core import module_row_value
        except Exception:
            module_row_value = None
        try:
            if module_row_value is not None:
                value = await module_row_value(self.bot, int(guild_id), str(module))
                return True if value is None else bool(value)
            row = await self.bot.db.fetchone(
                "SELECT enabled FROM module_settings WHERE guild_id=? AND module=?",
                (int(guild_id), str(module)),
            )
        except Exception:
            return True  # table absente : ne casse pas un serveur existant
        return True if row is None else bool(row["enabled"])

    async def explicit_rule(self, guild_id: int, author: Any, name: str):
        """Read the exact role rules persisted by Setup V2.

        Discord includes @everyone in Member.roles (its id equals guild.id), so
        one role query covers both @everyone and custom roles. If several roles
        disagree, an explicit deny wins.
        """
        role_ids = sorted(_role_ids(author))
        if not role_ids:
            return None, ""
        marks = ",".join("?" for _ in role_ids)
        try:
            rows = await self.bot.db.fetchall(
                "SELECT role_id, decision FROM command_role_permissions "
                "WHERE guild_id=? AND command_name=? "
                f"AND role_id IN ({marks})",
                (int(guild_id), name, *role_ids),
            )
        except Exception:
            logger.exception("Lecture des règles Setup impossible guild=%s", guild_id)
            return None, ""

        denied = [row for row in rows if str(row["decision"]).casefold() == "deny"]
        allowed = [row for row in rows if str(row["decision"]).casefold() == "allow"]
        if denied:
            source = "everyone" if all(int(row["role_id"]) == int(guild_id) for row in denied) else "role"
            return False, source
        if allowed:
            source = "everyone" if all(int(row["role_id"]) == int(guild_id) for row in allowed) else "role"
            return True, source
        return None, ""

    async def has_staff_role(self, guild_id: int, author: Any) -> bool:
        try:
            conf = await self.bot.db.get_guild_config(int(guild_id))
        except Exception:
            return False
        role_id = conf["mod_role"] if conf is not None else None
        if not role_id:
            return False
        try:
            return int(role_id) in _role_ids(author)
        except (TypeError, ValueError):
            return False

    async def can_use_embed_builder(self, guild_id: int, author: Any) -> bool:
        perms = _permissions(author)
        if perms is not None and (
            getattr(perms, "manage_messages", False)
            or getattr(perms, "manage_guild", False)
        ):
            return True
        try:
            rows = await self.bot.db.fetchall(
                "SELECT role_id FROM embed_allowed_roles WHERE guild_id = ?",
                (int(guild_id),),
            )
        except Exception:
            return False
        allowed = {int(r["role_id"]) for r in rows}
        return bool(allowed & _role_ids(author))

    async def ai_features(self, guild_id: int) -> dict[str, bool]:
        defaults = {"commands_enabled": True, "image_generation_enabled": True}
        try:
            row = await self.bot.db.fetchone(
                "SELECT commands_enabled, image_generation_enabled "
                "FROM ai_feature_settings_v2 WHERE guild_id=?",
                (int(guild_id),),
            )
        except Exception:
            return defaults
        if row is None:
            return defaults
        return {
            "commands_enabled": bool(row["commands_enabled"]),
            "image_generation_enabled": bool(row["image_generation_enabled"]),
        }


def backend_for(bot) -> Backend:
    existing = getattr(bot, "sentrix_access_backend", None)
    if existing is not None:
        return existing
    backend = Backend(bot)
    try:
        bot.sentrix_access_backend = backend
    except Exception:
        pass
    return backend


async def evaluate(bot, *, command_name: Any, author: Any, guild: Any) -> AccessDecision:
    """LA décision. Appelée à l'identique par le préfixe et par le slash."""
    name = normalise(command_name)
    if not name:
        return _deny("Commande impossible à identifier.", "invalid")
    # Resolution du nom : une sous-commande declaree plus stricte que son groupe garde
    # son nom complet, toutes les autres heritent de leur racine. Fait ici et pas
    # seulement dans le garde, pour que tout appelant direct obtienne la meme decision.
    name = resolve_name(name)

    backend = backend_for(bot)
    user_id = getattr(author, "id", None)
    try:
        user_id = int(user_id) if user_id is not None else None
    except (TypeError, ValueError):
        user_id = None

    # (1) blacklist globale
    if user_id is not None:
        reason = await backend.blacklist_reason(user_id)
        if reason is not None and not await backend.is_global_owner(user_id):
            return _deny(
                f"Vous n'êtes pas autorisé à utiliser SentriX. Raison : {reason}",
                "global-blacklist",
            )

    is_global_owner = user_id is not None and await backend.is_global_owner(user_id)

    # (2) owner-only : aucune règle serveur ne peut l'ouvrir
    if name in OWNER_ONLY_COMMANDS:
        if is_global_owner:
            return AccessDecision(True, policy="owner-global")
        return _deny(
            "Cette commande est réservée au **propriétaire global de SentriX**.",
            "owner-global",
        )

    # (3) owner global : passe partout ailleurs, y compris modules coupés
    if is_global_owner:
        return AccessDecision(True, policy="owner-global-bypass")

    guild_id = getattr(guild, "id", None)

    # Hors serveur : seules les commandes publiques répondent
    if guild_id is None:
        if name in PUBLIC_COMMANDS:
            return AccessDecision(True, policy="public-dm")
        return _deny("Cette commande doit être utilisée dans un serveur.", "guild-required")
    guild_id = int(guild_id)

    # (4) module désactivé
    module = module_for_command(name)
    if module and not await backend.module_enabled(guild_id, module):
        label = MODULE_LABELS.get(module, module)
        return _deny(
            f"Le module **{label}** est désactivé sur ce serveur. "
            "Un administrateur peut le réactiver dans `+setup` ou `/setup`.",
            f"module:{module}:off",
        )

    # (4b) sous-interrupteurs IA
    if module == "ai" and name not in AI_ALWAYS_ALLOWED:
        features = await backend.ai_features(guild_id)
        if name in AI_IMAGE_COMMANDS and not features["image_generation_enabled"]:
            return _deny(
                "La **génération d'images IA** est désactivée sur ce serveur.",
                "ai:image-off",
            )
        if not features["commands_enabled"]:
            return _deny(
                "Les **commandes IA** sont désactivées sur ce serveur.",
                "ai:commands-off",
            )

    # (4c) NIVEAU 4 — proprietaire du SERVEUR uniquement.
    # Place AVANT les regles Setup, le bypass proprietaire et le bypass Administrateur :
    # un administrateur Discord ne doit pas pouvoir detruire le serveur.
    if name in GUILD_OWNER_COMMANDS:
        if _is_guild_owner(author, guild):
            return AccessDecision(True, policy="guild-owner-only")
        if name == "dmall":
            return _deny(
                "Cette commande est reservee au **proprietaire du serveur**.\n"
                "Elle envoie un message prive a l'ensemble des membres non-bot : "
                "le role Administrateur ne suffit pas.",
                "guild-owner-only",
            )
        return _deny(
            "Cette commande est reservee au **proprietaire du serveur**.\n"
            "Elle detruit des donnees de maniere irreversible : le role Administrateur "
            "ne suffit pas.",
            "guild-owner-only",
        )

    # Recovery exception: an explicit deny may restrict the guild owner for
    # dangerous commands, but +setup and /setup must always stay reachable so
    # the owner can repair the permission matrix.
    if name == "setup" and _is_guild_owner(author, guild):
        return AccessDecision(True, policy="guild-owner:setup-recovery")

    # (5) et (6) règle explicite Setup
    explicit, source = await backend.explicit_rule(guild_id, author, name)
    if explicit is False:
        return _deny(
            "Cette commande a été **désactivée pour votre rôle** dans les "
            "permissions SentriX.",
            f"setup:{source}:deny",
        )
    if explicit is True:
        return AccessDecision(True, policy=f"setup:{source}:allow")

    # (7) propriétaire du serveur Discord
    if _is_guild_owner(author, guild):
        return AccessDecision(True, policy="guild-owner")

    # (8) Administrateur Discord
    if _is_administrator(author):
        return AccessDecision(True, policy="administrator")

    # (9) permission Discord requise
    if name in CUSTOM_PERMISSION_COMMANDS:
        if await backend.can_use_embed_builder(guild_id, author):
            return AccessDecision(True, policy="embed-staff")
        return _deny(
            "**Permission requise :** Gérer les messages / Gérer le serveur / "
            "rôle autorisé pour `+embed`.",
            "embed-staff",
        )

    required = DISCORD_PERMISSION_COMMANDS.get(name)
    if required is not None:
        if _has_discord_permission(author, required):
            return AccessDecision(True, policy=f"discord:{required}")
        if required in STAFF_ROLE_FALLBACK_PERMISSIONS and await backend.has_staff_role(
            guild_id, author
        ):
            return AccessDecision(True, policy="staff-role")
        return _deny(
            f"**Permission requise :** {permission_label(required)} "
            "ou un rôle autorisé dans `Setup > Permissions`.",
            f"discord:{required}",
        )

    # (10) commande publique
    if name in PUBLIC_COMMANDS:
        return AccessDecision(True, policy="public")

    # (11) fail-closed
    for category, names in CATEGORY_COMMANDS.items():
        if name in names:
            return _deny(
                "**Permission requise :** Administrateur ou un rôle autorisé "
                "dans `Setup > Permissions`.",
                f"categorie:{category}",
            )
    return _deny(
        "Cette commande n'a pas encore de niveau d'accès public validé.\n"
        "**Permission requise :** Administrateur.",
        "fail-closed",
    )


__all__ = [
    "AccessDecision", "Backend", "backend_for", "evaluate", "normalise",
    "access_tier", "help_requirement", "permission_label", "module_for_command",
    "PUBLIC_COMMANDS", "OWNER_ONLY_COMMANDS", "CUSTOM_PERMISSION_COMMANDS",
    "GUILD_OWNER_COMMANDS", "DISCORD_PERMISSION_COMMANDS", "CATEGORY_COMMANDS",
    "KNOWN_COMMANDS",
    "PERMISSION_LABELS", "PERMISSIONS_SENSIBLES", "MODULE_LABELS", "DENIAL_HEADER",
]
