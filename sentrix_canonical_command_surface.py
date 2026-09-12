"""Surface slash canonique SentriX.

Une seule couche décide ici des noms visibles et du rangement des commandes slash.
Les commandes préfixées ``+`` et leurs callbacks métier restent inchangés.
"""
from __future__ import annotations

import logging

from discord.ext import commands

import sentrix_v95_runtime as v95
import sentrix_v98_slash as v98

logger = logging.getLogger("bot.canonical-command-surface")
_INSTALLED = False

ROOTS = {
    "ai": "ia", "info": "infos", "utility": "outils", "economy": "economie",
    "level": "niveaux", "levels": "niveaux", "game": "jeux", "games": "jeux",
    "music": "musique", "events": "evenements", "ticket": "tickets",
    "sanctions": "moderation", "moderation": "moderation", "security": "securite",
    "config": "configuration", "server": "serveur", "role": "roles", "roles": "roles",
    "embeds": "messages", "owner": "proprietaire", "more": "outils",
    "giveaway": "concours", "invites": "invitations", "notifications": "notifications",
    "social": "social", "stats": "statistiques",
}
ROOT_BACK = {
    "tickets": "ticket", "moderation": "moderation", "securite": "security",
    "configuration": "config", "economie": "economy", "niveaux": "level",
    "jeux": "game", "roles": "role", "serveur": "server", "musique": "music",
}
ROOT_DESCRIPTIONS = {
    "ia": "Assistant IA, images et outils intelligents.",
    "infos": "Informations sur les membres, salons, serveur et bot.",
    "outils": "Outils pratiques et commandes du quotidien.",
    "economie": "Solde, banque, boutique et récompenses.",
    "niveaux": "Niveaux, XP, réputation et classements.",
    "jeux": "Mini-jeux et activités communautaires.",
    "musique": "Lecture audio, file d'attente et playlists.",
    "evenements": "Événements, tournois et activités.",
    "tickets": "Tickets, support et réglages des tickets.",
    "moderation": "Sanctions et outils de modération.",
    "securite": "AutoMod, anti-raid, anti-nuke et sécurité.",
    "configuration": "Configuration générale de SentriX.",
    "serveur": "Structure et administration du serveur.",
    "roles": "Rôles, panels et vérification.",
    "messages": "Embeds, annonces et design des messages.",
    "proprietaire": "Commandes réservées au propriétaire de SentriX.",
    "concours": "Concours et tirages au sort.",
    "invitations": "Invitations, classements et bonus.",
    "notifications": "Notifications sociales et messages d'accueil.",
    "social": "Fonctions sociales de SentriX.",
    "statistiques": "Statistiques et diagnostics.",
}

# Alias généraux. Les alias musique ont leur propre table pour éviter qu'un nom comme
# ``clear`` change aussi la commande de modération.
LEAVES = {
    "userinfo": "utilisateur", "membercount": "membres", "emoji-list": "emojis",
    "reminder-list": "rappels", "reminder-cancel": "annuler-rappel",
    "report-bug": "signaler-bug", "fact-check": "verifier-info",
    "image-prompt": "prompt-image", "ai-translate": "traduire", "bot-status": "statut",
    "server-growth": "croissance", "command-stats": "stats-commandes",
    "unban": "debannir", "kick": "expulser", "warn": "avertir",
    "warnings": "avertissements", "unwarn": "retirer-avertissement",
    "clearwarnings": "vider-avertissements", "clear": "nettoyer",
    "slowmode": "mode-lent", "lock": "verrouiller", "unlock": "deverrouiller",
    "nickname": "pseudo", "resetnick": "reset-pseudo", "giverole": "donner-role",
    "removerole": "retirer-role", "modhistory": "historique",
    "ticket-reopen": "rouvrir", "tickettranscript": "transcription",
    "sanctiondm": "message-sanction", "security-check": "verification",
    "security-level": "niveau", "permission-audit": "audit-permissions",
    "server-backup": "sauvegarder", "server-restore": "restaurer",
    "lockdown-server": "verrouillage-total", "unlock-server": "deverrouillage-total",
    "blacklist-users": "utilisateurs-bloques", "blacklist-list": "liste-noire",
    "blacklist-add": "bloquer", "blacklist-remove": "debloquer",
    "whitelist-domain": "autoriser-domaine", "unwhitelist-domain": "retirer-domaine",
    "syncbl": "sync-liste-noire", "unsyncbl": "desync-liste-noire",
    "setprefix": "prefixe", "setmodrole": "role-modo", "config-view": "voir",
    "config-reset": "reinitialiser", "create-server": "creer-structure",
    "delete-channel": "supprimer-salon", "disablecommand": "desactiver-commande",
    "enablecommand": "activer-commande", "ignorechannel": "ignorer-salon",
    "unignorechannel": "reactiver-salon", "setwarnrole": "role-avertissement",
    "setwarnbanthreshold": "limite-avertissements", "set-xp": "definir-xp",
    "add-xp": "ajouter-xp", "reset-levels": "reset-niveaux",
    "levelcheck": "verifier-niveau", "levelrepair": "reparer-niveau",
    "designsetup": "design", "embedconfig": "reglages-embed",
    "reactionrole-add": "ajouter-reaction", "reactionrole-remove": "retirer-reaction",
    "reactionrole-list": "liste-reactions", "balance": "solde", "daily": "quotidien",
    "weekly": "hebdo", "work": "travailler", "pay": "payer",
    "inventory": "inventaire", "economyleaderboard": "classement",
    "leaderboard-levels": "classement", "set-level-role": "role-niveau",
    "remove-level-role": "retirer-role-niveau", "voice-time": "temps-vocal",
    "set-bio": "bio", "ticket": "ouvrir", "ticketsetup": "configuration",
    "ticketpanel": "creer-panel", "ticketpanel-toggle": "activer-panel",
    "tickettype": "type", "ticketform": "formulaire", "ticketconfig": "reglages",
    "ticketlogs": "logs", "ticketlimit": "limite", "ticketautoclose": "fermeture-auto",
    "giveaway-list": "liste", "giveaway-create": "creer", "giveaway-end": "terminer",
    "giveaway-reroll": "relancer", "giveaway-cancel": "annuler",
    "event-join": "rejoindre", "event-leave": "quitter", "event-list": "liste",
    "event-create": "creer", "event-cancel": "annuler",
    "tournament-join": "rejoindre-tournoi", "tournament-list": "tournois",
    "tournament-create": "creer-tournoi", "tournament-start": "lancer-tournoi",
    "invite-leaderboard": "classement", "invited-by": "invite-par",
    "addbonusinvites": "ajouter-bonus", "removebonusinvites": "retirer-bonus",
    "invitebonushistory": "historique-bonus", "notifs-ping": "ajouter",
    "notifs-list": "liste", "notifs-remove": "supprimer", "welcome-config": "bienvenue",
    "rps": "pierre-feuille-ciseaux", "guess-number": "devine-nombre",
    "trivia": "quiz", "tictactoe": "morpion", "hangman": "pendu",
    "math-quiz": "calcul", "slots": "machine-a-sous", "coinflip": "pile-ou-face",
    "dice": "des", "highlow": "plus-ou-moins", "memory": "memoire",
    "scramble": "mot-melange", "wordgame": "jeu-mots", "emojiquiz": "quiz-emoji",
    "colorquiz": "quiz-couleur", "fasttype": "vitesse", "connect4": "puissance4",
    "numberduel": "duel-nombres", "reactionduel": "duel-reaction",
    "quizduel": "duel-quiz", "wordrace": "course-mots",
    "reactionevent": "course-reaction", "guessrace": "course-devinette",
    "mathrace": "course-calcul", "emoji-race": "course-emoji", "dungeon": "donjon",
    "mining": "minage", "fishing": "peche", "treasure": "tresor", "hunt": "chasse",
    "explore": "explorer", "gamehistory": "historique", "gameprofile": "profil",
    "gamestats": "stats", "gametop": "classement", "dailygames": "jeux-du-jour",
}
MUSIC_LEAVES = {
    "join": "rejoindre", "leave": "quitter", "play": "jouer", "pause": "pause",
    "resume": "reprendre", "skip": "suivant", "previous": "precedent",
    "stop": "arreter", "queue": "voir", "nowplaying": "en-cours",
    "volume": "volume", "loop": "boucle", "shuffle": "melanger",
    "remove": "retirer", "clear": "vider", "seek": "position",
    "autoplay": "lecture-auto",
}
PLAYLIST_LEAVES = {
    "create": "sauvegarder", "import": "importer", "add": "ajouter",
    "list": "liste", "show": "infos", "play": "charger", "remove": "retirer",
    "clear": "vider", "rename": "renommer", "delete": "supprimer",
}
DUPLICATES = frozenset({
    "leaderboard-money", "me", "rank", "buyrole", "ask", "chat", "chat-reset",
    "embed-create", "latency", "levelroles",
})
BUCKETS = {
    ("ticket", "panel"): "panneaux", ("ticket", "config"): "configuration",
    ("ticket", "manage"): "gestion", ("ticket", "stats"): "historique",
    ("moderation", "members"): "membres", ("moderation", "cases"): "dossiers",
    ("moderation", "emoji"): "emojis", ("moderation", "general"): "outils",
    ("security", "lists"): "listes", ("security", "backup"): "sauvegarde",
    ("security", "general"): "outils", ("config", "commands"): "commandes",
    ("config", "channels"): "salons", ("config", "levels"): "niveaux",
    ("economy", "wallet"): "portefeuille", ("economy", "rewards"): "recompenses",
    ("economy", "shop"): "boutique", ("economy", "ranking"): "classement",
    ("economy", "admin"): "administration", ("economy", "general"): "outils",
    ("level", "profile"): "profil", ("level", "ranking"): "classement",
    ("level", "general"): "outils", ("game", "quick"): "rapides",
    ("game", "races"): "courses", ("game", "adventure"): "aventure",
    ("game", "general"): "divers", ("role", "manage"): "gestion",
    ("role", "panels"): "panneaux", ("role", "reactions"): "reactions",
    ("role", "general"): "divers", ("server", "build"): "creation",
    ("server", "channels"): "salons", ("server", "backup"): "sauvegarde",
    ("server", "manage"): "gestion", ("server", "general"): "divers",
}


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

    def should_expose(command: commands.Command) -> bool:
        name, simple = _qualified(command), _simple(command)
        if getattr(command, "hidden", False) or name in DUPLICATES or simple in DUPLICATES:
            return False
        return bool(old_should_expose(command))

    def group_for(command: commands.Command):
        qualified, simple = _qualified(command), _simple(command)
        if qualified.startswith("music playlist "):
            return "musique", PLAYLIST_LEAVES.get(simple, simple)
        if qualified.startswith("music "):
            return "musique", MUSIC_LEAVES.get(simple, simple)
        root, leaf = old_group_for(command)
        root = ROOTS.get(str(root).casefold(), str(root).casefold())
        return root, LEAVES.get(qualified, LEAVES.get(simple, leaf))

    def bucket(root_name: str, target: v95.SlashTarget) -> str:
        root = str(root_name).casefold()
        original_root = ROOT_BACK.get(root, root)
        original_name = str(target.original_name or "").casefold().strip()
        simple = original_name.split(" ")[-1]
        if root == "musique" or original_root == "music":
            if original_name.startswith("music playlist "):
                return "playlist"
            if simple in {"queue", "shuffle", "remove", "clear"}:
                return "file"
            return "lecture"
        original_bucket = old_bucket(original_root, target)
        return BUCKETS.get((original_root, original_bucket), original_bucket)

    def leaf(_root: str, _bucket: str, target: v95.SlashTarget) -> str:
        return v95._safe_name(target.leaf_name)

    def chunks(bucket_name: str, count: int) -> list[str]:
        base = v95._safe_name(bucket_name)
        return [base] + [
            v95._safe_name(f"{base}-suite" if index == 2 else f"{base}-suite-{index}")
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
    v98.semantic_leaf = leaf
    v98._chunk_group_names = chunks
    v98.FORCED_SEMANTIC_ROOTS = frozenset({
        "tickets", "moderation", "securite", "configuration", "economie",
        "niveaux", "jeux", "roles", "serveur", "musique",
    })
    v95.GROUP_DESCRIPTIONS.update(ROOT_DESCRIPTIONS)
    v98.SUBGROUP_DESCRIPTIONS.update({
        ("musique", "lecture"): "Lecture et contrôle du lecteur musical.",
        ("musique", "file"): "Afficher et gérer la file d'attente.",
        ("musique", "playlist"): "Sauvegarder, importer et charger vos playlists.",
    })
    logger.warning("Surface slash canonique active : noms français, doublons masqués, /musique structuré.")


__all__ = ["install", "ROOTS", "LEAVES", "MUSIC_LEAVES", "PLAYLIST_LEAVES"]
