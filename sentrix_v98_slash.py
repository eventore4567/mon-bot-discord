"""SentriX V98 — surface slash organisée par sous-groupes sémantiques.

V98 reste un adaptateur d'interface : toutes les commandes ``+`` et leur logique métier
restent propriétaires de l'exécution. La couche ne fait que construire une arborescence
Discord lisible juste avant ``CommandTree.sync``.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict

import discord
from discord import app_commands

import sentrix_v95_runtime as v95

logger = logging.getLogger("bot.v98-slash")

# Les catégories éditoriales historiques gardent leur logique. Seuls les noms visibles
# sont normalisés pour une surface slash plus compacte.
CATEGORY_ROOT_OVERRIDES = {
    "levels": "level",
    "games": "game",
    "roles": "role",
    "sanctions": "moderation",
}

ROOT_DESCRIPTIONS = {
    "level": "Niveaux, XP, réputation et classements.",
    "game": "Mini-jeux et activités communautaires.",
    "role": "Rôles, panels et vérification.",
}

# Les grosses familles sont toujours structurées. Les petites restent plates afin de ne
# pas ajouter un niveau inutile.
FORCED_SEMANTIC_ROOTS = frozenset({
    "ticket",
    "moderation",
    "security",
    "config",
    "economy",
    "level",
    "game",
    "role",
    "server",
})

SUBGROUP_DESCRIPTIONS = {
    ("ticket", "panel"): "Créer et gérer les panels de tickets.",
    ("ticket", "config"): "Configurer les tickets et leur comportement.",
    ("ticket", "manage"): "Ouvrir, fermer et administrer les tickets.",
    ("ticket", "stats"): "Transcripts, statistiques et historique des tickets.",

    ("moderation", "sanctions"): "Bans, mutes, avertissements et quarantaine.",
    ("moderation", "messages"): "Messages, salons, verrouillage et slowmode.",
    ("moderation", "members"): "Membres, pseudos, vocal et rôles individuels.",
    ("moderation", "cases"): "Dossiers, historique et notifications de sanctions.",
    ("moderation", "emoji"): "Gestion des emojis du serveur.",
    ("moderation", "general"): "Autres outils de modération.",

    ("security", "automod"): "Filtres AutoMod et protections anti-abus.",
    ("security", "antinuke"): "Anti-nuke, verrouillage et réactions d'urgence.",
    ("security", "lists"): "Blacklist, whitelist et synchronisation des listes.",
    ("security", "audit"): "Audits, diagnostics et niveau de sécurité.",
    ("security", "backup"): "Sauvegarde et restauration du serveur.",
    ("security", "general"): "Autres outils de sécurité.",

    ("config", "general"): "Réglages généraux de SentriX.",
    ("config", "commands"): "Activation, désactivation et règles des commandes.",
    ("config", "channels"): "Salons, logs et destinations configurées.",
    ("config", "roles"): "Rôles automatiques et rôles de configuration.",
    ("config", "levels"): "Réglages XP, niveaux et récompenses.",
    ("config", "reputation"): "Réglages de réputation.",
    ("config", "design"): "Design, embeds et apparence.",

    ("economy", "wallet"): "Solde, banque et transferts.",
    ("economy", "rewards"): "Récompenses quotidiennes et activités rémunérées.",
    ("economy", "shop"): "Boutique, achats et inventaire.",
    ("economy", "ranking"): "Classements économiques.",
    ("economy", "admin"): "Administration de l'économie et de la boutique.",
    ("economy", "games"): "Jeux liés à l'économie.",
    ("economy", "general"): "Autres fonctions économiques.",

    ("level", "profile"): "Profil, niveau, activité et réputation.",
    ("level", "ranking"): "Classements de niveaux et réputation.",
    ("level", "xp"): "Gestion de l'XP et des niveaux.",
    ("level", "reputation"): "Administration de la réputation.",
    ("level", "general"): "Autres fonctions de niveaux.",

    ("game", "quick"): "Mini-jeux rapides et quiz.",
    ("game", "casino"): "Jeux de hasard et de cartes.",
    ("game", "duels"): "Duels et jeux à deux.",
    ("game", "races"): "Courses et événements compétitifs.",
    ("game", "adventure"): "Exploration, pêche, minage et aventure.",
    ("game", "stats"): "Profils, historique et classements des jeux.",
    ("game", "general"): "Autres mini-jeux.",

    ("role", "manage"): "Ajouter, retirer et gérer les rôles.",
    ("role", "panels"): "Panels et menus de rôles.",
    ("role", "reactions"): "Rôles par réaction.",
    ("role", "verification"): "Vérification et rôles associés.",
    ("role", "general"): "Autres outils de rôles.",

    ("server", "build"): "Construction et structure du serveur.",
    ("server", "channels"): "Gestion des salons et catégories.",
    ("server", "backup"): "Sauvegarde et restauration du serveur.",
    ("server", "manage"): "Administration générale du serveur.",
    ("server", "general"): "Autres outils serveur.",
}

# Alias uniquement visuels. La callback conserve toujours _sentrix_original_command.
LEAF_ALIASES = {
    # Tickets
    ("ticket", "panel", "ticketpanel"): "create",
    ("ticket", "panel", "ticketpanel-toggle"): "toggle",
    ("ticket", "config", "ticketsetup"): "setup",
    ("ticket", "config", "tickettype"): "type",
    ("ticket", "config", "ticketform"): "form",
    ("ticket", "config", "ticketconfig"): "settings",
    ("ticket", "config", "ticketlogs"): "logs",
    ("ticket", "config", "ticketlimit"): "limit",
    ("ticket", "config", "ticketautoclose"): "auto-close",
    ("ticket", "manage", "ticket"): "open",
    ("ticket", "manage", "ticket-reopen"): "reopen",
    ("ticket", "stats", "tickettranscript"): "transcript",
    ("ticket", "stats", "ticketstats"): "stats",

    # AutoMod / sécurité
    ("security", "automod", "antispam"): "spam",
    ("security", "automod", "antilink"): "links",
    ("security", "automod", "antiinvite"): "invites",
    ("security", "automod", "antimention"): "mentions",
    ("security", "automod", "anticaps"): "caps",
    ("security", "automod", "antiemoji"): "emoji",
    ("security", "automod", "antiraid"): "raid",
    ("security", "automod", "antibot"): "bots",
    ("security", "automod", "antiaccount"): "accounts",
    ("security", "automod", "antiscam"): "scam",
    ("security", "automod", "automod-status"): "status",
    ("security", "automod", "automod-history"): "history",
    ("security", "automod", "automod-escalation"): "escalation",
}


def _command_key(target: v95.SlashTarget) -> str:
    """Nom historique normalisé, sans toucher au chemin stocké pour les permissions."""
    text = str(target.original_name or "").casefold().strip()
    text = re.sub(r"\s+", "-", text)
    return text


def _starts_or_contains(name: str, *tokens: str) -> bool:
    return any(name == token or name.startswith(token + "-") or token in name for token in tokens)


def semantic_bucket(root_name: str, target: v95.SlashTarget) -> str:
    """Retourne le sous-groupe visible le plus naturel pour une commande."""
    root = str(root_name).casefold()
    name = _command_key(target)

    if root == "ticket":
        if "panel" in name:
            return "panel"
        if any(token in name for token in ("setup", "config", "type", "form", "logs", "limit", "autoclose", "role")):
            return "config"
        if any(token in name for token in ("transcript", "stats", "history")):
            return "stats"
        return "manage"

    if root == "moderation":
        if name in {
            "ban", "tempban", "unban", "kick", "mute", "unmute", "warn", "unwarn",
            "warnings", "clearwarnings", "quarantine", "unquarantine",
        } or _starts_or_contains(name, "ban", "mute", "warn", "quarantine"):
            return "sanctions"
        if name in {"case", "modhistory", "sanctiondm"} or any(
            token in name for token in ("case", "history", "sanctiondm")
        ):
            return "cases"
        if name in {"addemoji", "deleteemoji"} or "emoji" in name:
            return "emoji"
        if name in {
            "clear", "purge", "say", "slowmode", "lock", "unlock", "hide", "show",
        } or any(token in name for token in ("purge", "slowmode", "lock", "unlock")):
            return "messages"
        if name in {
            "nickname", "resetnick", "move", "disconnect", "giverole", "removerole",
            "role-snapshot", "role-restore",
        } or any(token in name for token in ("nickname", "resetnick", "disconnect", "giverole", "removerole")):
            return "members"
        return "general"

    if root == "security":
        if name.startswith("antinuke") or name in {
            "lockdown-server", "unlock-server", "panic",
        }:
            return "antinuke"
        if name.startswith("blacklist") or name in {
            "syncbl", "unsyncbl", "whitelist-domain", "unwhitelist-domain",
            "unblacklist-user",
        }:
            return "lists"
        if name in {"server-backup", "server-restore"} or "backup" in name or "restore" in name:
            return "backup"
        if name in {
            "security-check", "permission-audit", "security-level",
        } or any(token in name for token in ("audit", "diagnostic", "security-check", "security-level")):
            return "audit"
        if name.startswith("anti") or name.startswith("automod"):
            return "automod"
        return "general"

    if root == "config":
        if any(token in name for token in ("disablecommand", "enablecommand", "command-channel", "commands")):
            return "commands"
        if (
            "channel" in name
            or name.startswith("log")
            or name.endswith("-logs")
            or "ignorechannel" in name
            or "unignorechannel" in name
        ):
            return "channels"
        if any(token in name for token in ("autorole", "warnrole", "modrole", "rolepanel", "reactionrole")):
            return "roles"
        if any(token in name for token in ("set-xp", "add-xp", "reset-level", "levelcheck", "levelrepair", "levelrole")):
            return "levels"
        if name.startswith("rep") or "reputation" in name:
            return "reputation"
        if any(token in name for token in ("design", "embed", "theme", "icon", "announce")):
            return "design"
        return "general"

    if root == "economy":
        if name in {"balance", "economy", "deposit", "withdraw", "banque", "pay"}:
            return "wallet"
        if name in {"daily", "weekly", "work", "rob"}:
            return "rewards"
        if name in {"shop", "buy", "buyrole", "inventory", "sell"}:
            return "shop"
        if "leaderboard" in name or name in {"economy-top", "money-top"}:
            return "ranking"
        if name in {"shopsetup", "shoppanel", "shoprole", "give-money", "reset-economy", "gamesetup"}:
            return "admin"
        if name in {"gamble", "drop"}:
            return "games"
        return "general"

    if root == "level":
        if name in {"leaderboard-levels", "repleaderboard", "leaderboard"} or "leaderboard" in name:
            return "ranking"
        if name in {"set-xp", "add-xp", "reset-levels", "levelcheck", "levelrepair"} or "xp" in name:
            return "xp"
        if name.startswith("rep") and name not in {"rep", "reputation"}:
            return "reputation"
        if name in {"level", "profile", "set-bio", "rep", "reputation", "voice-time", "stats"}:
            return "profile"
        return "general"

    if root == "game":
        if name in {"blackjack", "slots", "coinflip", "dice", "luckyroll", "highlow", "gamble"}:
            return "casino"
        if name in {"duel", "connect4", "numberduel", "reactionduel", "quizduel", "tictactoe"} or "duel" in name:
            return "duels"
        if any(token in name for token in ("race", "event", "lastmessage", "fasttype")):
            return "races"
        if name in {"adventure", "dungeon", "mining", "fishing", "treasure", "hunt", "explore"}:
            return "adventure"
        if any(token in name for token in ("history", "profile", "stats", "top", "dailygames")):
            return "stats"
        if name in {
            "rps", "guess-number", "trivia", "hangman", "math-quiz", "memory",
            "reaction", "scramble", "wordgame", "emojiquiz", "colorquiz",
        }:
            return "quick"
        return "general"

    if root == "role":
        if name.startswith("reactionrole") or "reaction-role" in name:
            return "reactions"
        if name.startswith("verify") or "verification" in name:
            return "verification"
        if "panel" in name:
            return "panels"
        if any(token in name for token in ("roleall", "massrole", "giverole", "removerole", "role-snapshot", "role-restore")):
            return "manage"
        return "general"

    if root == "server":
        if any(token in name for token in ("backup", "restore")):
            return "backup"
        if any(token in name for token in ("channel", "category")):
            return "channels"
        if any(token in name for token in ("create-server", "wipe-server", "builder", "create-sentrix")):
            return "build"
        if any(token in name for token in ("server", "member", "role")):
            return "manage"
        return "general"

    return "general"


def semantic_leaf(root_name: str, bucket: str, target: v95.SlashTarget) -> str:
    key = _command_key(target)
    alias = LEAF_ALIASES.get((root_name, bucket, key))
    return v95._safe_name(alias or target.leaf_name)


def _chunk_group_names(bucket: str, count: int) -> list[str]:
    if count <= 1:
        return [v95._safe_name(bucket)]
    names: list[str] = []
    for index in range(count):
        if index == 0:
            candidate = bucket
        elif index == 1:
            candidate = f"{bucket}-plus"
        elif index == 2:
            candidate = f"{bucket}-extra"
        else:
            candidate = f"{bucket}-more-{index + 1}"
        names.append(v95._safe_name(candidate))
    return names


def _subgroup_description(root: str, bucket: str, index: int, total: int) -> str:
    base = SUBGROUP_DESCRIPTIONS.get(
        (root, bucket),
        f"Commandes {bucket} de {root}.",
    )
    if total > 1:
        base = f"{base} Partie {index}/{total}."
    return base[:100]


def _add_flat_root(
    bot,
    root: app_commands.Group,
    members: list[v95.SlashTarget],
    report: dict[str, dict],
) -> None:
    used: set[str] = set()
    for target in members:
        leaf = v95._unique_leaf(target.leaf_name, used, target.original_name)
        callback, native = v95._make_callback(bot, target.command)
        slash = app_commands.Command(
            name=leaf,
            description=v95._description(target.command),
            callback=callback,
        )
        root.add_command(slash)
        path = f"/{root.name} {slash.name}"
        report[path] = {
            "original": target.original_name,
            "category": root.name,
            "subcategory": None,
            "native_options": bool(native),
        }


def _add_semantic_root(
    bot,
    root: app_commands.Group,
    members: list[v95.SlashTarget],
    report: dict[str, dict],
) -> None:
    buckets: dict[str, list[v95.SlashTarget]] = defaultdict(list)
    for target in members:
        buckets[semantic_bucket(root.name, target)].append(target)

    used_group_names: set[str] = set()
    for bucket, bucket_members in sorted(buckets.items()):
        chunks = [
            bucket_members[index:index + v95.MAX_CHILDREN]
            for index in range(0, len(bucket_members), v95.MAX_CHILDREN)
        ]
        candidate_names = _chunk_group_names(bucket, len(chunks))

        for chunk_index, (group_candidate, chunk) in enumerate(
            zip(candidate_names, chunks),
            start=1,
        ):
            group_name = v95._unique_leaf(
                group_candidate,
                used_group_names,
                f"{root.name}:{bucket}:{chunk_index}",
            )
            subgroup = app_commands.Group(
                name=group_name,
                description=_subgroup_description(
                    root.name, bucket, chunk_index, len(chunks)
                ),
                parent=root,
            )
            root.add_command(subgroup)

            used_leaf_names: set[str] = set()
            for target in chunk:
                base_leaf = semantic_leaf(root.name, bucket, target)
                leaf = v95._unique_leaf(
                    base_leaf,
                    used_leaf_names,
                    target.original_name,
                )
                callback, native = v95._make_callback(bot, target.command)
                slash = app_commands.Command(
                    name=leaf,
                    description=v95._description(target.command),
                    callback=callback,
                )
                subgroup.add_command(slash)
                path = f"/{root.name} {subgroup.name} {slash.name}"
                report[path] = {
                    "original": target.original_name,
                    "category": root.name,
                    "subcategory": subgroup.name,
                    "native_options": bool(native),
                }

    if len(root.commands) > v95.MAX_CHILDREN:
        raise RuntimeError(
            f"V98 group too large: {root.name} has {len(root.commands)} subgroups"
        )


def _add_grouped_surface_v98(bot) -> dict[str, dict]:
    """Construit la surface finale sans aucun sous-groupe générique ``page-N``."""
    tree = bot.tree
    targets = v95._build_targets(bot)
    v95._remove_old_roots(tree)
    report: dict[str, dict] = {}

    by_root: dict[str, list[v95.SlashTarget]] = defaultdict(list)
    for target in targets:
        by_root[target.root_name].append(target)

    for root_name, members in sorted(by_root.items()):
        safe_root = v95._safe_name(root_name)
        root = app_commands.Group(
            name=safe_root,
            description=v95.GROUP_DESCRIPTIONS.get(
                safe_root,
                f"Commandes {safe_root} de SentriX.",
            )[:100],
        )

        needs_semantic = (
            safe_root in FORCED_SEMANTIC_ROOTS
            or len(members) > v95.MAX_CHILDREN
        )
        if needs_semantic:
            _add_semantic_root(bot, root, members, report)
        else:
            _add_flat_root(bot, root, members, report)

        tree.add_command(root, override=True)

    roots = list(
        tree.get_commands(
            guild=None,
            type=discord.AppCommandType.chat_input,
        )
    )
    if len(roots) > v95.MAX_ROOT_COMMANDS:
        raise RuntimeError(
            f"V98 slash root budget exceeded: {len(roots)}/{v95.MAX_ROOT_COMMANDS}"
        )
    if any(" page-" in path for path in report):
        raise RuntimeError("V98 invariant violated: page-N subgroup leaked into slash tree")

    # Compatibilité avec les diagnostics V95/V97 + nouveaux attributs explicites V98.
    bot._sentrix_v95_slash_mapping = report
    bot._sentrix_v95_slash_root_count = len(roots)
    bot._sentrix_v98_slash_mapping = report
    bot._sentrix_v98_slash_root_count = len(roots)

    logger.warning(
        "V98 slash prête : %s actions, %s racines, sous-groupes sémantiques actifs.",
        len(report),
        len(roots),
    )
    return report


def install() -> None:
    """Installe V98 après le bootstrap V95, sans toucher aux callbacks métier."""
    if getattr(v95, "_sentrix_v98_grouped_slash", False):
        return

    v95.CATEGORY_ROOTS.update(CATEGORY_ROOT_OVERRIDES)
    v95.GROUP_DESCRIPTIONS.update(ROOT_DESCRIPTIONS)
    v95._add_grouped_surface = _add_grouped_surface_v98
    v95._sentrix_v98_grouped_slash = True

    logger.warning(
        "V98 slash actif : level/game/role normalisés, sanctions fusionnées, page-N supprimées."
    )


__all__ = [
    "CATEGORY_ROOT_OVERRIDES",
    "FORCED_SEMANTIC_ROOTS",
    "install",
    "semantic_bucket",
    "semantic_leaf",
    "_add_grouped_surface_v98",
]
