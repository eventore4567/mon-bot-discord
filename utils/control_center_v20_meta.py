"""Métadonnées et catalogue partagé du centre de contrôle SentriX V20."""
from __future__ import annotations

import inspect
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import discord
from discord.ext import commands

import main as bot_main

STATE_ACTIVE = "ACTIF"
STATE_INACTIVE = "INACTIF"
STATE_UNCONFIGURED = "NON CONFIGURÉ"
STATE_ERROR = "ERREUR DE CONFIGURATION"
BAR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

PERMISSION_LABELS = {
    "administrator": "Administrateur",
    "manage_guild": "Gérer le serveur",
    "manage_channels": "Gérer les salons",
    "manage_roles": "Gérer les rôles",
    "manage_messages": "Gérer les messages",
    "manage_nicknames": "Gérer les pseudos",
    "moderate_members": "Modérer les membres",
    "kick_members": "Expulser des membres",
    "ban_members": "Bannir des membres",
    "move_members": "Déplacer des membres",
    "manage_emojis_and_stickers": "Gérer les expressions",
    "view_audit_log": "Voir les logs d’audit",
    "send_messages": "Envoyer des messages",
    "embed_links": "Intégrer des liens",
    "attach_files": "Joindre des fichiers",
}

SETUP_CATEGORIES: OrderedDict[str, dict[str, Any]] = OrderedDict(
    [
        ("moderation", {"title": "Modération", "description": "Sanctions, avertissements, rôles staff et messages privés de sanction.", "bot_permissions": ("ban_members", "kick_members", "moderate_members", "manage_messages")}),
        ("security", {"title": "Sécurité", "description": "AutoMod, anti-spam, anti-raid, liens, mentions, exceptions et protection du serveur.", "bot_permissions": ("manage_messages", "moderate_members", "view_audit_log")}),
        ("logs", {"title": "Logs", "description": "Journaux messages, membres, rôles, salons, vocal, modération, tickets, sécurité et système.", "bot_permissions": ("view_audit_log", "send_messages", "embed_links")}),
        ("tickets", {"title": "Tickets", "description": "Panels, catégories, support, ping, transcript, limites et comportement des tickets.", "bot_permissions": ("manage_channels", "manage_roles", "send_messages", "embed_links", "attach_files")}),
        ("welcome", {"title": "Bienvenue et départ", "description": "Salons, messages, image de bienvenue et rôle automatique.", "bot_permissions": ("send_messages", "embed_links", "manage_roles")}),
        ("roles", {"title": "Rôles", "description": "Autorole, rôles membres, vérification, notifications et rôles spéciaux.", "bot_permissions": ("manage_roles",)}),
        ("levels_economy", {"title": "Niveaux et économie", "description": "XP, niveaux, argent, banque, récompenses, annonces et boutique.", "bot_permissions": ("send_messages", "manage_roles")}),
        ("notifications", {"title": "Notifications", "description": "YouTube, Twitch et TikTok : salon, rôle, texte, image et état.", "bot_permissions": ("send_messages", "embed_links")}),
        ("ai", {"title": "IA", "description": "Assistant, génération d’images, accès membres, mémoire et limites par serveur.", "bot_permissions": ("send_messages", "attach_files", "embed_links")}),
    ]
)

HELP_CATEGORY_ORDER = ["Modération", "Informations", "Économie", "Jeux", "Tickets", "IA", "Administration", "Notifications"]
HELP_COG_MAP = {
    "Moderation": "Modération",
    "Automod": "Administration",
    "Security": "Administration",
    "SecurityTools": "Administration",
    "Configuration": "Administration",
    "Logs": "Administration",
    "Verification": "Administration",
    "ServerBuilder": "Administration",
    "Owner": "Administration",
    "EmbedBuilder": "Administration",
    "Design": "Administration",
    "Economy": "Économie",
    "Levels": "Économie",
    "GamesEconomy": "Jeux",
    "Minigames": "Jeux",
    "Music": "Jeux",
    "Events": "Jeux",
    "Tickets": "Tickets",
    "Ai": "IA",
    "Notifications": "Notifications",
    "Utility": "Informations",
    "Stats": "Informations",
    "Invites": "Informations",
}

SECURITY_FIELDS = OrderedDict([
    ("antispam", "Anti-spam"),
    ("antiraid", "Anti-raid"),
    ("antilink", "Anti-lien"),
    ("antiinvite", "Anti-invitation"),
    ("antimention", "Anti-ping"),
    ("antiscam", "Anti-scam"),
    ("antinuke", "Anti-nuke"),
    ("antiaccount", "Anti-comptes récents"),
])

LOG_TYPES_SHOWN = OrderedDict([
    ("messages", "Messages"),
    ("moderation", "Modération"),
    ("roles", "Rôles"),
    ("server", "Salons"),
    ("voice", "Vocal"),
    ("members", "Membres"),
    ("tickets", "Tickets"),
    ("automod", "Sécurité"),
    ("system", "SentriX"),
])

ROLE_COLUMNS = {
    "moderation_staff_role": ("mod_role", "Rôle staff"),
    "moderation_warn_role": ("warn_role", "Rôle d’avertissement"),
    "welcome_autorole": ("autorole", "Rôle automatique"),
    "roles_autorole": ("autorole", "Rôle automatique"),
    "roles_member": ("member_role", "Rôle membre"),
    "roles_verify": ("verify_role", "Rôle de vérification"),
    "roles_booster": ("booster_role", "Rôle booster"),
}

CHANNEL_COLUMNS = {
    "welcome_channel": ("welcome_channel", "Salon de bienvenue"),
    "goodbye_channel": ("goodbye_channel", "Salon de départ"),
    "levels_channel": ("level_channel", "Salon des niveaux"),
    "tickets_log_channel": ("ticket_log_channel", "Logs tickets"),
}


@dataclass
class ModuleSnapshot:
    key: str
    state: str
    lines: list[str] = field(default_factory=list)
    missing_permissions: list[str] = field(default_factory=list)
    problem: str | None = None

    @property
    def complete(self) -> bool:
        return self.state in {STATE_ACTIVE, STATE_INACTIVE}


def _row_get(row, key: str, default=None):
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        try:
            value = getattr(row, key)
        except Exception:
            return default
    return default if value is None else value


def _human_permission(name: str) -> str:
    return PERMISSION_LABELS.get(name, name.replace("_", " ").capitalize())


def _state_for_resource(guild: discord.Guild, resource_id: int | None, kind: str) -> tuple[str, str]:
    if not resource_id:
        return STATE_UNCONFIGURED, "Non configuré"
    resource = guild.get_role(int(resource_id)) if kind == "role" else guild.get_channel(int(resource_id))
    if resource is None:
        return STATE_ERROR, "Ressource supprimée ou introuvable"
    return STATE_ACTIVE, getattr(resource, "mention", str(resource))


def _bot_missing_permissions(guild: discord.Guild, names: tuple[str, ...]) -> list[str]:
    me = guild.me
    if me is None:
        return [_human_permission(name) for name in names]
    perms = me.guild_permissions
    return [_human_permission(name) for name in names if not getattr(perms, name, False)]


def _cog_name(command: commands.Command) -> str:
    return getattr(command.cog, "qualified_name", "Utility") if command.cog else "Utility"


def _help_category(command: commands.Command) -> str:
    name = command.root_parent.name.casefold() if command.root_parent else command.name.casefold()
    if name in getattr(bot_main, "DISCORD_PERMISSION_COMMANDS", {}):
        return "Modération"
    if name in getattr(bot_main, "OWNER_ONLY_COMMANDS", frozenset()):
        return "Administration"
    return HELP_COG_MAP.get(_cog_name(command), "Informations")


def _all_help_commands(bot: commands.Bot) -> list[commands.Command]:
    rows: list[commands.Command] = []
    seen: set[str] = set()
    for command in bot.walk_commands():
        if command.hidden:
            continue
        key = command.qualified_name.casefold()
        if key in seen:
            continue
        seen.add(key)
        rows.append(command)
    return sorted(rows, key=lambda c: (_help_category(c), c.qualified_name.casefold()))


def _slash_map(bot: commands.Bot) -> dict[str, str]:
    result: dict[str, str] = {}
    def walk(node, parent=""):
        qualified = f"{parent} {node.name}".strip()
        result[qualified.casefold()] = qualified
        for child in getattr(node, "commands", []):
            walk(child, qualified)
    for node in bot.tree.get_commands(type=discord.AppCommandType.chat_input):
        walk(node)
    return result


def _permission_from_checks(command: commands.Command) -> str | None:
    root = command.root_parent or command
    name = root.name.casefold()
    if name in getattr(bot_main, "OWNER_ONLY_COMMANDS", frozenset()) or _cog_name(command) == "Owner":
        return "Propriétaire global SentriX"
    required = getattr(bot_main, "DISCORD_PERMISSION_COMMANDS", {}).get(name)
    if required:
        return _human_permission(required)
    for check in getattr(command, "checks", []):
        qn = getattr(check, "__qualname__", "")
        if "is_bot_owner" in qn:
            return "Propriétaire global SentriX"
        try:
            closure = inspect.getclosurevars(check)
        except Exception:
            continue
        permission = closure.nonlocals.get("permission")
        if isinstance(permission, str):
            return _human_permission(permission)
        if "is_owner_or_admin" in qn:
            return "Administrateur"
    if name in getattr(bot_main, "PUBLIC_COMMANDS", frozenset()):
        return "Aucune permission spéciale"
    for _category, names in getattr(bot_main, "CATEGORY_COMMANDS", {}).items():
        if name in names:
            return "Administrateur ou gestionnaire global SentriX"
    return "Administrateur par sécurité"


def _command_description(command: commands.Command) -> str:
    value = (command.description or command.help or "Aucune description disponible.").strip()
    return value.split("\n", 1)[0][:350]


def _command_usage(command: commands.Command, prefix: str) -> str:
    signature = command.usage or getattr(command, "signature", "") or ""
    return f"{prefix}{command.qualified_name} {signature}".strip()


def _search_help(bot: commands.Bot, query: str) -> list[commands.Command]:
    needle = query.casefold().strip()
    ranked = []
    for command in _all_help_commands(bot):
        aliases = [a.casefold() for a in (command.aliases or [])]
        name = command.qualified_name.casefold()
        text = " ".join((name, *aliases, _command_description(command).casefold(), _help_category(command).casefold()))
        if needle not in text:
            continue
        rank = 0 if needle in {name, command.name.casefold(), *aliases} else 1 if name.startswith(needle) else 2
        ranked.append((rank, name, command))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in ranked]
