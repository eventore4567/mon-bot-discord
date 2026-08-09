"""Centre Operations SentriX : permissions, profils, diagnostics et résilience.

Cette couche ajoute des capacités transversales sans multiplier les commandes publiques :
- permissions par module basées sur des rôles ;
- fiche membre staff (sanctions, tickets, notes, activité, invites, AutoMod) ;
- événements de dossiers de modération (raison, annulation logique, notes) ;
- exceptions AutoMod par salon ou catégorie ;
- commandes personnalisées simples ;
- sauvegardes riches avec restauration partielle ;
- diagnostics persistants des permissions, panels et vues ;
- journal des erreurs runtime ;
- anti-raid adaptatif avec verrouillage temporaire et restauration automatique.

Les anciennes tables/commandes restent compatibles. Les modifications de dossier sont
additives : une sanction historique n'est jamais réécrite ni supprimée silencieusement.
"""
from __future__ import annotations

import asyncio
import difflib
import html
import json
import logging
import re
import time
import traceback
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

import discord
from discord.ext import commands, tasks

from database.db import now

logger = logging.getLogger("bot.operations")
_COG_NAME = "OperationsCenter"

MODULE_LABELS = {
    "moderation": "Modération",
    "security": "Sécurité",
    "tickets": "Tickets",
    "configuration": "Configuration",
    "economy": "Économie",
    "levels": "Niveaux",
    "ai": "IA",
    "events": "Événements",
    "music": "Musique",
    "utility": "Utilitaires",
}

MODULE_COG_NAMES = {
    "Moderation": "moderation",
    "Automod": "security",
    "SecurityTools": "security",
    "SecurityCommandCenter": "security",
    "SecurityV2Runtime": "security",
    "Tickets": "tickets",
    "Configuration": "configuration",
    "Economy": "economy",
    "Levels": "levels",
    "AI": "ai",
    "Events": "events",
    "Music": "music",
    "Utility": "utility",
}

ROOT_MODULES = {
    "ban": "moderation", "tempban": "moderation", "unban": "moderation",
    "kick": "moderation", "mute": "moderation", "unmute": "moderation",
    "warn": "moderation", "unwarn": "moderation", "warnings": "moderation",
    "clearwarnings": "moderation", "case": "moderation", "modhistory": "moderation",
    "clear": "moderation", "slowmode": "moderation", "lock": "moderation",
    "unlock": "moderation", "nickname": "moderation", "resetnick": "moderation",
    "security": "security", "antinuke": "security", "antiraid": "security",
    "antispam": "security", "antilink": "security", "antiinvite": "security",
    "antimention": "security", "anticaps": "security", "antiemoji": "security",
    "antiaccount": "security", "antibot": "security", "antiscam": "security",
    "panic": "security", "quarantine": "security", "unquarantine": "security",
    "ticket": "tickets", "ticketpanel": "tickets", "tickettype": "tickets",
    "ticketform": "tickets", "ticketconfig": "tickets", "ticketlogs": "tickets",
    "ticketlimit": "tickets", "ticketautoclose": "tickets", "ticketstats": "tickets",
    "tickettranscript": "tickets", "setup": "configuration", "create-server": "configuration",
    "rolepanel": "configuration", "verify-panel": "configuration", "logs": "configuration",
    "economy-system": "economy", "balance": "economy", "daily": "economy",
    "weekly": "economy", "work": "economy", "pay": "economy", "shop": "economy",
    "buy": "economy", "inventory": "economy", "sell": "economy",
    "level-system": "levels", "level": "levels", "profile": "levels",
    "leaderboard-levels": "levels", "stats": "levels", "ai": "ai",
    "sentrix": "ai", "image": "ai", "code": "ai", "giveaway-create": "events",
    "event-create": "events", "tournament-create": "events", "play": "music",
    "queue": "music", "skip": "music", "stop": "music", "volume": "music",
}

CUSTOM_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
REQUIRED_BOT_PERMISSIONS = (
    "view_audit_log", "manage_guild", "manage_channels", "manage_roles",
    "manage_messages", "moderate_members", "kick_members", "ban_members",
)


async def _ensure_tables(bot: commands.Bot) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS module_role_permissions (
            guild_id INTEGER NOT NULL,
            module TEXT NOT NULL,
            role_id INTEGER NOT NULL,
            granted_by INTEGER,
            created_at INTEGER NOT NULL,
            PRIMARY KEY (guild_id, module, role_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS staff_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            note TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS moderation_case_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            case_number INTEGER NOT NULL,
            actor_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            value TEXT,
            created_at INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS automod_scope_rules (
            guild_id INTEGER NOT NULL,
            target_type TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_by INTEGER,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (guild_id, target_type, target_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS custom_commands_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            response TEXT NOT NULL,
            allowed_role_id INTEGER,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE (guild_id, name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS dashboard_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            target TEXT,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ticket_transcripts_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            ticket_id INTEGER NOT NULL,
            channel_id INTEGER,
            user_id INTEGER,
            generated_by INTEGER NOT NULL,
            html_content TEXT NOT NULL,
            search_text TEXT NOT NULL DEFAULT '',
            generated_at INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS runtime_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            source TEXT NOT NULL,
            error_type TEXT NOT NULL,
            message TEXT NOT NULL,
            traceback_text TEXT,
            created_at INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS component_checks (
            guild_id INTEGER NOT NULL,
            check_name TEXT NOT NULL,
            status TEXT NOT NULL,
            details TEXT,
            checked_at INTEGER NOT NULL,
            PRIMARY KEY (guild_id, check_name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS raid_events_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            score INTEGER NOT NULL,
            join_count INTEGER NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS raid_lockdowns_v2 (
            guild_id INTEGER PRIMARY KEY,
            active INTEGER NOT NULL DEFAULT 0,
            expires_at INTEGER,
            previous_verification_level INTEGER,
            overwrites_json TEXT NOT NULL DEFAULT '{}',
            updated_at INTEGER NOT NULL
        )
        """,
    ]
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_module_role_permissions_guild ON module_role_permissions (guild_id, module)",
        "CREATE INDEX IF NOT EXISTS idx_staff_notes_guild_user ON staff_notes (guild_id, user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_case_events_guild_case ON moderation_case_events (guild_id, case_number, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_dashboard_audit_guild_time ON dashboard_audit_log (guild_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_transcripts_guild_ticket ON ticket_transcripts_v2 (guild_id, ticket_id, generated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_runtime_errors_time ON runtime_errors (guild_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_raid_events_guild_time ON raid_events_v2 (guild_id, created_at DESC)",
    ]
    for statement in statements + indexes:
        await bot.db.execute(statement)


def _module_for_command(command: commands.Command | None) -> str | None:
    if command is None:
        return None
    root = command.root_parent or command
    name = root.name.casefold()
    if name in ROOT_MODULES:
        return ROOT_MODULES[name]
    cog_name = getattr(command, "cog_name", None)
    return MODULE_COG_NAMES.get(str(cog_name))


def _serialise_overwrite(overwrite: discord.PermissionOverwrite) -> dict:
    allow, deny = overwrite.pair()
    return {"allow": int(allow.value), "deny": int(deny.value)}


def _snapshot_overwrites(channel: discord.abc.GuildChannel) -> list[dict]:
    result = []
    for target, overwrite in channel.overwrites.items():
        result.append({
            "target_id": int(target.id),
            "target_type": "role" if isinstance(target, discord.Role) else "member",
            **_serialise_overwrite(overwrite),
        })
    return result


def _channel_snapshot(channel: discord.abc.GuildChannel) -> dict:
    base = {
        "id": int(channel.id),
        "name": channel.name,
        "position": int(channel.position),
        "category": channel.category.name if channel.category else None,
        "overwrites": _snapshot_overwrites(channel),
    }
    if isinstance(channel, discord.TextChannel):
        base.update({
            "type": "text",
            "topic": channel.topic,
            "nsfw": bool(channel.nsfw),
            "slowmode_delay": int(channel.slowmode_delay),
        })
    elif isinstance(channel, discord.VoiceChannel):
        base.update({
            "type": "voice",
            "bitrate": int(channel.bitrate),
            "user_limit": int(channel.user_limit),
        })
    elif isinstance(channel, discord.CategoryChannel):
        base["type"] = "category"
    else:
        base["type"] = "other"
    return base


def _role_snapshot(role: discord.Role) -> dict:
    return {
        "id": int(role.id), "name": role.name, "position": int(role.position),
        "color": int(role.color.value), "permissions": int(role.permissions.value),
        "hoist": bool(role.hoist), "mentionable": bool(role.mentionable),
    }


class OperationsCenter(commands.Cog, name=_COG_NAME):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._module_cache: dict[int, tuple[float, dict[str, set[int]]]] = {}
        self._scope_cache: dict[int, tuple[float, set[int]]] = {}
        self._custom_cache: dict[int, tuple[float, dict[str, dict]]] = {}
        self._joins: dict[int, deque[tuple[float, int, str, int, bool]]] = defaultdict(lambda: deque(maxlen=60))
        self._diagnostic_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._raid_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._component_tick = 0
        self.maintenance_loop.start()

    def cog_unload(self):
        self.maintenance_loop.cancel()

    # -------------------------------------------------------------- permissions modules
    async def get_module_roles(self, guild_id: int, *, fresh: bool = False) -> dict[str, set[int]]:
        cached = self._module_cache.get(guild_id)
        if not fresh and cached and time.time() - cached[0] < 30:
            return cached[1]
        rows = await self.bot.db.fetchall(
            "SELECT module, role_id FROM module_role_permissions WHERE guild_id = ?",
            (guild_id,),
        )
        result: dict[str, set[int]] = defaultdict(set)
        for row in rows:
            result[str(row["module"])].add(int(row["role_id"]))
        final = dict(result)
        self._module_cache[guild_id] = (time.time(), final)
        return final

    async def set_module_role(self, guild_id: int, module: str, role_id: int, enabled: bool, actor_id: int) -> None:
        module = str(module).casefold()
        if module not in MODULE_LABELS:
            raise ValueError("Module SentriX inconnu.")
        if enabled:
            await self.bot.db.execute(
                "INSERT OR REPLACE INTO module_role_permissions "
                "(guild_id, module, role_id, granted_by, created_at) VALUES (?, ?, ?, ?, ?)",
                (guild_id, module, int(role_id), int(actor_id), now()),
            )
        else:
            await self.bot.db.execute(
                "DELETE FROM module_role_permissions WHERE guild_id = ? AND module = ? AND role_id = ?",
                (guild_id, module, int(role_id)),
            )
        self._module_cache.pop(guild_id, None)

    async def module_permission_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            return True
        module = _module_for_command(ctx.command)
        if module is None:
            return True
        if ctx.author.id == ctx.guild.owner_id or ctx.author.guild_permissions.administrator:
            return True
        rules = await self.get_module_roles(ctx.guild.id)
        required_roles = rules.get(module, set())
        if not required_roles:
            return True
        if any(role.id in required_roles for role in ctx.author.roles):
            return True

        # Les anciens gestionnaires complets/catégoriels restent compatibles, mais cette
        # couche ne remplace jamais les checks Discord/modération déjà présents ensuite.
        category = {
            "security": "securite", "tickets": "tickets", "moderation": "moderation",
            "configuration": "configuration", "economy": "economie", "ai": "ai",
        }.get(module, "complete")
        try:
            if await self.bot.db.is_bot_manager(ctx.guild.id, ctx.author.id) and await self.bot.db.has_manager_permission(ctx.guild.id, ctx.author.id, category):
                return True
        except Exception:
            pass
        raise commands.CheckFailure(
            f"Ce module SentriX est limité à des rôles autorisés ({MODULE_LABELS[module]})."
        )

    # -------------------------------------------------------------- AutoMod scope
    async def get_automod_exempt_channel_ids(self, guild: discord.Guild, *, fresh: bool = False) -> set[int]:
        cached = self._scope_cache.get(guild.id)
        if not fresh and cached and time.time() - cached[0] < 20:
            return set(cached[1])
        rows = await self.bot.db.fetchall(
            "SELECT target_type, target_id FROM automod_scope_rules "
            "WHERE guild_id = ? AND enabled = 1",
            (guild.id,),
        )
        result: set[int] = set()
        for row in rows:
            target_type, target_id = str(row["target_type"]), int(row["target_id"])
            if target_type == "channel":
                result.add(target_id)
            elif target_type == "category":
                category = guild.get_channel(target_id)
                if isinstance(category, discord.CategoryChannel):
                    result.update(int(ch.id) for ch in category.channels)
        self._scope_cache[guild.id] = (time.time(), set(result))
        return result

    async def set_automod_scope(self, guild: discord.Guild, target_type: str, target_id: int, enabled: bool, actor_id: int) -> None:
        if target_type not in {"channel", "category"}:
            raise ValueError("La cible doit être un salon ou une catégorie.")
        channel = guild.get_channel(int(target_id))
        if channel is None:
            raise ValueError("Salon ou catégorie introuvable.")
        if target_type == "category" and not isinstance(channel, discord.CategoryChannel):
            raise ValueError("La cible choisie n'est pas une catégorie.")
        if target_type == "channel" and isinstance(channel, discord.CategoryChannel):
            raise ValueError("Choisissez le type catégorie pour cette cible.")
        await self.bot.db.execute(
            "INSERT INTO automod_scope_rules (guild_id, target_type, target_id, enabled, updated_by, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, target_type, target_id) DO UPDATE SET "
            "enabled=excluded.enabled, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
            (guild.id, target_type, int(target_id), int(bool(enabled)), int(actor_id), now()),
        )
        self._scope_cache.pop(guild.id, None)

    def attach_automod_scope(self) -> None:
        automod = self.bot.get_cog("Automod")
        if automod is None or getattr(automod, "_sentrix_ops_scope", False):
            return
        original = automod.get_ignored_channels_cached
        service = self

        async def scoped(guild_id: int):
            existing = set(await original(guild_id))
            guild = service.bot.get_guild(int(guild_id))
            if guild is not None:
                existing.update(await service.get_automod_exempt_channel_ids(guild))
            return existing

        automod.get_ignored_channels_cached = scoped
        automod._sentrix_ops_scope = True
        logger.info("AutoMod par salon/catégorie activé.")

    # -------------------------------------------------------------- custom commands
    async def get_custom_commands(self, guild_id: int, *, fresh: bool = False) -> dict[str, dict]:
        cached = self._custom_cache.get(guild_id)
        if not fresh and cached and time.time() - cached[0] < 30:
            return cached[1]
        rows = await self.bot.db.fetchall(
            "SELECT id, name, response, allowed_role_id, enabled FROM custom_commands_v2 "
            "WHERE guild_id = ? AND enabled = 1",
            (guild_id,),
        )
        result = {str(row["name"]).casefold(): dict(row) for row in rows}
        self._custom_cache[guild_id] = (time.time(), result)
        return result

    async def save_custom_command(self, guild_id: int, name: str, response: str, actor_id: int, allowed_role_id: int | None = None, enabled: bool = True) -> None:
        name = str(name).strip().casefold()
        if not CUSTOM_NAME_RE.fullmatch(name):
            raise ValueError("Nom invalide : 1 à 32 caractères, lettres/chiffres/tiret/underscore.")
        if self.bot.get_command(name) is not None:
            raise ValueError("Ce nom est déjà utilisé par une commande SentriX.")
        response = str(response or "").strip()
        if not response or len(response) > 2000:
            raise ValueError("La réponse doit contenir entre 1 et 2 000 caractères.")
        ts = now()
        await self.bot.db.execute(
            "INSERT INTO custom_commands_v2 "
            "(guild_id, name, response, allowed_role_id, enabled, created_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, name) DO UPDATE SET response=excluded.response, "
            "allowed_role_id=excluded.allowed_role_id, enabled=excluded.enabled, updated_at=excluded.updated_at",
            (guild_id, name, response, allowed_role_id, int(bool(enabled)), actor_id, ts, ts),
        )
        self._custom_cache.pop(guild_id, None)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None or not message.content:
            return
        try:
            prefixes = await self.bot.get_prefix(message)
        except Exception:
            prefixes = "+"
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        prefix = next((p for p in prefixes if message.content.startswith(p)), None)
        if not prefix:
            return
        rest = message.content[len(prefix):].strip()
        if not rest:
            return
        name = rest.split(maxsplit=1)[0].casefold()
        if self.bot.get_command(name) is not None:
            return
        commands_map = await self.get_custom_commands(message.guild.id)
        item = commands_map.get(name)
        if not item:
            return
        allowed_role_id = item.get("allowed_role_id")
        if allowed_role_id and isinstance(message.author, discord.Member):
            if not message.author.guild_permissions.administrator and not any(r.id == int(allowed_role_id) for r in message.author.roles):
                return
        text = str(item["response"])
        replacements = {
            "{user}": message.author.mention,
            "{username}": message.author.display_name,
            "{server}": message.guild.name,
            "{channel}": message.channel.mention,
            "{member_count}": str(message.guild.member_count or 0),
        }
        for key, value in replacements.items():
            text = text.replace(key, value)
        try:
            await message.reply(text[:2000], mention_author=False, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        except discord.HTTPException:
            pass

    # -------------------------------------------------------------- staff member profile
    async def member_profile(self, guild: discord.Guild, user_id: int) -> dict:
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.HTTPException:
                member = None
        warnings = await self.bot.db.fetchall(
            "SELECT id, moderator_id, reason, timestamp FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY timestamp DESC LIMIT 50",
            (guild.id, user_id),
        )
        sanctions = await self.bot.db.fetchall(
            "SELECT case_number, moderator_id, action, reason, duration_seconds, created_at "
            "FROM sanctions WHERE guild_id = ? AND user_id = ? ORDER BY case_number DESC LIMIT 100",
            (guild.id, user_id),
        )
        tickets = await self.bot.db.fetchall(
            "SELECT id, channel_id, status, category, priority, claimed_by, created_at, closed_at, rating "
            "FROM tickets WHERE guild_id = ? AND user_id = ? ORDER BY id DESC LIMIT 50",
            (guild.id, user_id),
        )
        notes = await self.bot.db.fetchall(
            "SELECT id, author_id, note, created_at FROM staff_notes WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT 50",
            (guild.id, user_id),
        )
        automod = await self.bot.db.fetchall(
            "SELECT filter_name, action, reason, timestamp FROM automod_logs WHERE guild_id = ? AND user_id = ? ORDER BY timestamp DESC LIMIT 50",
            (guild.id, user_id),
        )
        level = await self.bot.db.fetchone(
            "SELECT xp, level FROM levels WHERE guild_id = ? AND user_id = ?", (guild.id, user_id)
        )
        economy = await self.bot.db.fetchone(
            "SELECT cash, bank FROM economy WHERE guild_id = ? AND user_id = ?", (guild.id, user_id)
        )
        invite_total = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM member_invites WHERE guild_id = ? AND inviter_id = ? AND left_at IS NULL",
            (guild.id, user_id),
        )
        joined = await self.bot.db.fetchone(
            "SELECT inviter_id, joined_at, account_age_days FROM member_invites WHERE guild_id = ? AND member_id = ? ORDER BY joined_at DESC LIMIT 1",
            (guild.id, user_id),
        )
        return {
            "user": {
                "id": user_id,
                "display_name": member.display_name if member else str(user_id),
                "avatar_url": str(member.display_avatar.url) if member else None,
                "joined_at": int(member.joined_at.timestamp()) if member and member.joined_at else None,
                "created_at": int(member.created_at.timestamp()) if member else None,
                "roles": [{"id": r.id, "name": r.name} for r in member.roles if r != guild.default_role] if member else [],
            },
            "warnings": [dict(row) for row in warnings],
            "sanctions": [dict(row) for row in sanctions],
            "tickets": [dict(row) for row in tickets],
            "notes": [dict(row) for row in notes],
            "automod": [dict(row) for row in automod],
            "level": dict(level) if level else {"xp": 0, "level": 0},
            "economy": dict(economy) if economy else {"cash": 0, "bank": 0},
            "invites": {"total": int(invite_total["n"] if invite_total else 0), "joined": dict(joined) if joined else None},
        }

    async def add_staff_note(self, guild_id: int, user_id: int, actor_id: int, note: str) -> int:
        note = str(note or "").strip()
        if not note or len(note) > 1500:
            raise ValueError("La note doit contenir entre 1 et 1 500 caractères.")
        cur = await self.bot.db.execute(
            "INSERT INTO staff_notes (guild_id, user_id, author_id, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, actor_id, note, now()),
        )
        return int(cur.lastrowid)

    # -------------------------------------------------------------- moderation cases
    async def case_details(self, guild_id: int, case_number: int) -> dict | None:
        row = await self.bot.db.fetchone(
            "SELECT * FROM sanctions WHERE guild_id = ? AND case_number = ?", (guild_id, case_number)
        )
        if not row:
            return None
        events = await self.bot.db.fetchall(
            "SELECT id, actor_id, event_type, value, created_at FROM moderation_case_events "
            "WHERE guild_id = ? AND case_number = ? ORDER BY created_at ASC, id ASC",
            (guild_id, case_number),
        )
        result = dict(row)
        result["events"] = [dict(item) for item in events]
        result["status"] = "active"
        result["effective_reason"] = result.get("reason")
        for event in events:
            if event["event_type"] == "reason":
                result["effective_reason"] = event["value"]
            elif event["event_type"] == "void":
                result["status"] = "void"
            elif event["event_type"] == "restore":
                result["status"] = "active"
        return result

    async def add_case_event(self, guild_id: int, case_number: int, actor_id: int, event_type: str, value: str = "") -> None:
        event_type = str(event_type).casefold()
        if event_type not in {"reason", "void", "restore", "note"}:
            raise ValueError("Type de modification de dossier inconnu.")
        if not await self.bot.db.fetchone(
            "SELECT 1 FROM sanctions WHERE guild_id = ? AND case_number = ?", (guild_id, case_number)
        ):
            raise ValueError("Dossier introuvable.")
        value = str(value or "").strip()[:1500]
        if event_type in {"reason", "note"} and not value:
            raise ValueError("Ajoutez un texte pour cette modification.")
        await self.bot.db.execute(
            "INSERT INTO moderation_case_events (guild_id, case_number, actor_id, event_type, value, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, case_number, actor_id, event_type, value, now()),
        )

    # -------------------------------------------------------------- transcript HTML
    async def generate_ticket_transcript(self, guild: discord.Guild, ticket_id: int, generated_by: int) -> dict:
        ticket = await self.bot.db.fetchone(
            "SELECT * FROM tickets WHERE guild_id = ? AND id = ?", (guild.id, ticket_id)
        )
        if not ticket:
            raise ValueError("Ticket introuvable.")
        channel_id = int(ticket["channel_id"] or 0)
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Le salon du ticket n'existe plus : transcript Discord impossible à régénérer.")
        messages = []
        try:
            async for message in channel.history(limit=1000, oldest_first=True):
                messages.append(message)
        except discord.Forbidden as exc:
            raise ValueError("SentriX n'a pas la permission de lire l'historique du ticket.") from exc

        rows = []
        search_parts = []
        for message in messages:
            author = html.escape(str(message.author))
            content = html.escape(message.content or "").replace("\n", "<br>")
            created = message.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            attachment_links = " ".join(
                f'<a href="{html.escape(a.url, quote=True)}" rel="noopener">Pièce jointe</a>'
                for a in message.attachments
            )
            rows.append(
                f'<article><header><b>{author}</b><time>{created}</time></header>'
                f'<div>{content or "<i>Message sans texte</i>"}</div>'
                f'<footer>{attachment_links}</footer></article>'
            )
            search_parts.append(f"{message.author} {message.content or ''}")

        page = f"""<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SentriX — Ticket #{ticket_id}</title><style>body{{margin:0;background:#090b12;color:#f2f4ff;font:14px system-ui;padding:28px}}main{{max-width:980px;margin:auto}}h1{{margin:0 0 8px}}.meta{{color:#9aa3b9;margin-bottom:24px}}article{{padding:14px 16px;margin:9px 0;border:1px solid #273049;border-radius:12px;background:#111522}}header{{display:flex;justify-content:space-between;gap:15px;margin-bottom:8px}}time,footer{{color:#8f99b0;font-size:12px}}a{{color:#a99cff}}</style><main><h1>Ticket #{ticket_id}</h1><div class="meta">Serveur {html.escape(guild.name)} · Membre {ticket['user_id']} · {len(messages)} message(s)</div>{''.join(rows)}</main></html>"""
        search_text = "\n".join(search_parts)[:200000]
        cur = await self.bot.db.execute(
            "INSERT INTO ticket_transcripts_v2 "
            "(guild_id, ticket_id, channel_id, user_id, generated_by, html_content, search_text, generated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (guild.id, ticket_id, channel_id, int(ticket["user_id"]), generated_by, page, search_text, now()),
        )
        return {"id": int(cur.lastrowid), "messages": len(messages)}

    # -------------------------------------------------------------- rich backups
    def snapshot_server_rich(self, guild: discord.Guild) -> dict:
        return {
            "schema": "sentrix-rich-v1",
            "guild": {"id": guild.id, "name": guild.name, "verification_level": int(guild.verification_level.value)},
            "roles": [_role_snapshot(r) for r in guild.roles if r != guild.default_role and not r.managed],
            "channels": [_channel_snapshot(ch) for ch in guild.channels if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel))],
        }

    async def create_rich_backup(self, guild: discord.Guild, label: str, actor_id: int) -> int:
        label = str(label or "Backup complet").strip()[:80]
        data = self.snapshot_server_rich(guild)
        cur = await self.bot.db.execute(
            "INSERT INTO server_backups (guild_id, label, data_json, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild.id, label, json.dumps(data, ensure_ascii=False), actor_id, now()),
        )
        return int(cur.lastrowid)

    @staticmethod
    def _lookup_role(guild: discord.Guild, item: dict) -> discord.Role | None:
        role = guild.get_role(int(item.get("id") or 0))
        if role is not None:
            return role
        return discord.utils.find(lambda r: r.name == item.get("name") and not r.managed, guild.roles)

    @staticmethod
    def _lookup_channel(guild: discord.Guild, item: dict):
        channel = guild.get_channel(int(item.get("id") or 0))
        if channel is not None:
            return channel
        category_name = item.get("category")
        for ch in guild.channels:
            if ch.name == item.get("name") and (ch.category.name if ch.category else None) == category_name:
                return ch
        return None

    async def restore_backup_part(self, guild: discord.Guild, backup_id: int, part: str) -> dict:
        row = await self.bot.db.fetchone(
            "SELECT data_json FROM server_backups WHERE guild_id = ? AND id = ?", (guild.id, backup_id)
        )
        if not row:
            raise ValueError("Backup introuvable.")
        try:
            data = json.loads(row["data_json"] or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("Backup illisible.") from exc
        part = str(part).casefold()
        if part not in {"roles", "channels", "permissions"}:
            raise ValueError("Partie invalide : roles, channels ou permissions.")
        restored = 0

        if part == "roles":
            for item in data.get("roles", []):
                if self._lookup_role(guild, item) is not None:
                    continue
                try:
                    await guild.create_role(
                        name=str(item.get("name") or "Rôle restauré")[:100],
                        permissions=discord.Permissions(int(item.get("permissions") or 0)),
                        colour=discord.Colour(int(item.get("color") or 0)),
                        hoist=bool(item.get("hoist")),
                        mentionable=bool(item.get("mentionable")),
                        reason=f"SentriX : restauration partielle backup #{backup_id}",
                    )
                    restored += 1
                    await asyncio.sleep(0.08)
                except (discord.Forbidden, discord.HTTPException):
                    continue

        elif part == "channels":
            items = data.get("channels")
            # Compatibilité Security V2 historique.
            if not items:
                items = []
                for cat in data.get("categories", []):
                    items.append({"name": cat.get("name"), "type": "category", "category": None})
                    for ch in cat.get("channels", []):
                        items.append({**ch, "category": cat.get("name")})
                for ch in data.get("uncategorized", []):
                    items.append({**ch, "category": None})
            for item in [i for i in items if i.get("type") == "category"]:
                if self._lookup_channel(guild, item) is None:
                    try:
                        await guild.create_category(str(item.get("name") or "Catégorie restaurée")[:100], reason=f"SentriX backup #{backup_id}")
                        restored += 1
                    except (discord.Forbidden, discord.HTTPException):
                        pass
            for item in [i for i in items if i.get("type") in {"text", "voice"}]:
                if self._lookup_channel(guild, item) is not None:
                    continue
                category = discord.utils.get(guild.categories, name=item.get("category")) if item.get("category") else None
                try:
                    if item.get("type") == "voice":
                        await guild.create_voice_channel(str(item.get("name") or "vocal-restaure")[:100], category=category, reason=f"SentriX backup #{backup_id}")
                    else:
                        await guild.create_text_channel(
                            str(item.get("name") or "salon-restaure")[:100], category=category,
                            topic=item.get("topic"), nsfw=bool(item.get("nsfw")),
                            slowmode_delay=int(item.get("slowmode_delay") or 0),
                            reason=f"SentriX backup #{backup_id}",
                        )
                    restored += 1
                    await asyncio.sleep(0.08)
                except (discord.Forbidden, discord.HTTPException):
                    continue

        else:  # permissions
            for item in data.get("channels", []):
                channel = self._lookup_channel(guild, item)
                if channel is None or item.get("type") not in {"text", "voice", "category"}:
                    continue
                overwrites: dict[Any, discord.PermissionOverwrite] = {}
                for entry in item.get("overwrites", []):
                    target_id = int(entry.get("target_id") or 0)
                    target = guild.get_role(target_id) if entry.get("target_type") == "role" else guild.get_member(target_id)
                    if target is None:
                        continue
                    overwrite = discord.PermissionOverwrite.from_pair(
                        discord.Permissions(int(entry.get("allow") or 0)),
                        discord.Permissions(int(entry.get("deny") or 0)),
                    )
                    overwrites[target] = overwrite
                try:
                    await channel.edit(overwrites=overwrites, reason=f"SentriX : permissions backup #{backup_id}")
                    restored += 1
                    await asyncio.sleep(0.06)
                except (discord.Forbidden, discord.HTTPException):
                    continue
        return {"part": part, "restored": restored}

    # -------------------------------------------------------------- diagnostics/errors
    async def record_runtime_error(self, guild_id: int | None, source: str, exc: BaseException) -> None:
        try:
            trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-8000:]
            await self.bot.db.execute(
                "INSERT INTO runtime_errors (guild_id, source, error_type, message, traceback_text, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, str(source)[:120], type(exc).__name__[:120], str(exc)[:1500], trace, now()),
            )
        except Exception:
            logger.exception("Impossible de journaliser une erreur runtime SentriX.")

    async def _store_check(self, guild_id: int, name: str, status: str, details: str) -> None:
        await self.bot.db.execute(
            "INSERT INTO component_checks (guild_id, check_name, status, details, checked_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(guild_id, check_name) DO UPDATE SET "
            "status=excluded.status, details=excluded.details, checked_at=excluded.checked_at",
            (guild_id, name, status, details[:1500], now()),
        )

    async def run_diagnostics(self, guild: discord.Guild, *, deep: bool = False) -> dict:
        async with self._diagnostic_locks[guild.id]:
            checks: list[dict] = []
            me = guild.me
            if me is None:
                return {"ok": False, "checks": [{"name": "bot_member", "status": "error", "details": "Membre bot introuvable."}]}

            missing = [name for name in REQUIRED_BOT_PERMISSIONS if not getattr(me.guild_permissions, name, False)]
            status = "ok" if not missing else "error"
            details = "Toutes les permissions critiques sont présentes." if not missing else "Permissions manquantes : " + ", ".join(missing)
            checks.append({"name": "permissions", "status": status, "details": details})

            highest_other = max((r.position for r in guild.roles if not r.managed and r != guild.default_role), default=0)
            hierarchy_ok = me.top_role.position >= highest_other or me.guild_permissions.administrator
            checks.append({
                "name": "hierarchy", "status": "ok" if hierarchy_ok else "warning",
                "details": "Hiérarchie suffisante." if hierarchy_ok else "Le rôle SentriX n'est pas assez haut pour gérer certains rôles.",
            })

            persistent_views = len(getattr(getattr(self.bot, "_connection", None), "_view_store", object())._synced_message_views) if hasattr(getattr(getattr(self.bot, "_connection", None), "_view_store", None), "_synced_message_views") else 0
            checks.append({"name": "persistent_views", "status": "ok", "details": f"{persistent_views} vue(s) liée(s) à des messages en mémoire."})

            panel_specs = [
                ("ticket_panels", "SELECT channel_id, message_id FROM ticket_panels WHERE guild_id = ?"),
                ("ticket_panels_v2", "SELECT channel_id, message_id FROM ticket_panels_v2 WHERE guild_id = ? AND message_id IS NOT NULL"),
                ("self_role_panels", "SELECT channel_id, message_id FROM self_role_panels WHERE guild_id = ?"),
            ]
            for label, query in panel_specs:
                try:
                    rows = await self.bot.db.fetchall(query, (guild.id,))
                except Exception:
                    rows = []
                broken = 0
                if deep:
                    for row in rows[:50]:
                        channel = guild.get_channel(int(row["channel_id"] or 0))
                        if not isinstance(channel, discord.TextChannel):
                            broken += 1
                            continue
                        try:
                            message = await channel.fetch_message(int(row["message_id"]))
                            if not message.components:
                                broken += 1
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            broken += 1
                checks.append({
                    "name": label,
                    "status": "ok" if broken == 0 else "warning",
                    "details": f"{len(rows)} panneau(x) enregistré(s), {broken} problème(s) détecté(s).",
                })

            conf = await self.bot.db.get_guild_config(guild.id)
            log_ids = []
            if conf:
                for key in ("log_channel", "log_messages", "log_members", "log_voice", "log_roles", "log_server", "log_automod", "log_moderation"):
                    try:
                        value = conf[key]
                    except Exception:
                        value = None
                    if value:
                        log_ids.append(int(value))
            missing_logs = sum(1 for cid in set(log_ids) if guild.get_channel(cid) is None)
            checks.append({
                "name": "log_channels", "status": "ok" if not missing_logs else "warning",
                "details": f"{len(set(log_ids))} salon(s) de logs configuré(s), {missing_logs} introuvable(s).",
            })

            for check in checks:
                await self._store_check(guild.id, check["name"], check["status"], check["details"])
            return {"ok": not any(c["status"] == "error" for c in checks), "checks": checks}

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context):
        if ctx.guild and ctx.command:
            root = (ctx.command.root_parent or ctx.command).name.casefold()
            if root in {"create-server", "setup"}:
                asyncio.create_task(self.run_diagnostics(ctx.guild, deep=True))

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        original = getattr(error, "original", error)
        if isinstance(original, (commands.CommandNotFound, commands.CheckFailure, commands.BadArgument, commands.MissingRequiredArgument, commands.CommandOnCooldown)):
            return
        await self.record_runtime_error(ctx.guild.id if ctx.guild else None, f"command:{getattr(ctx.command, 'qualified_name', 'unknown')}", original)

    # -------------------------------------------------------------- smarter anti-raid
    def _raid_score(self, guild_id: int) -> tuple[int, dict]:
        current = time.time()
        q = self._joins[guild_id]
        while q and current - q[0][0] > 15:
            q.popleft()
        joins = list(q)
        count = len(joins)
        if not joins:
            return 0, {"joins": 0}
        young = sum(1 for _, age_days, _, _, _ in joins if age_days < 3)
        very_young = sum(1 for _, age_days, _, _, _ in joins if age_days < 1)
        bots = sum(1 for *_, is_bot in joins if is_bot)
        names = [name.casefold() for _, _, name, _, _ in joins]
        similar = 0
        for i, first in enumerate(names):
            if any(difflib.SequenceMatcher(None, first, other).ratio() >= 0.82 for other in names[i + 1:]):
                similar += 1
        score = min(100, count * 5 + young * 5 + very_young * 5 + similar * 4 + bots * 3)
        return score, {"joins": count, "young": young, "very_young": very_young, "similar_names": similar, "bots": bots}

    async def activate_raid_lockdown(self, guild: discord.Guild, *, seconds: int = 600) -> None:
        async with self._raid_locks[guild.id]:
            active = await self.bot.db.fetchone("SELECT active FROM raid_lockdowns_v2 WHERE guild_id = ?", (guild.id,))
            if active and active["active"]:
                return
            previous: dict[str, dict] = {}
            for channel in guild.text_channels:
                overwrite = channel.overwrites_for(guild.default_role)
                previous[str(channel.id)] = _serialise_overwrite(overwrite)
                if overwrite.send_messages is False:
                    continue
                overwrite.send_messages = False
                try:
                    await channel.set_permissions(guild.default_role, overwrite=overwrite, reason="SentriX : verrouillage anti-raid temporaire")
                except (discord.Forbidden, discord.HTTPException):
                    pass
            old_verification = int(guild.verification_level.value)
            try:
                if guild.verification_level != discord.VerificationLevel.highest:
                    await guild.edit(verification_level=discord.VerificationLevel.highest, reason="SentriX : anti-raid adaptatif")
            except (discord.Forbidden, discord.HTTPException):
                pass
            await self.bot.db.execute(
                "INSERT INTO raid_lockdowns_v2 (guild_id, active, expires_at, previous_verification_level, overwrites_json, updated_at) "
                "VALUES (?, 1, ?, ?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET active=1, expires_at=excluded.expires_at, "
                "previous_verification_level=excluded.previous_verification_level, overwrites_json=excluded.overwrites_json, updated_at=excluded.updated_at",
                (guild.id, now() + seconds, old_verification, json.dumps(previous), now()),
            )

    async def restore_raid_lockdown(self, guild: discord.Guild) -> None:
        async with self._raid_locks[guild.id]:
            row = await self.bot.db.fetchone("SELECT * FROM raid_lockdowns_v2 WHERE guild_id = ? AND active = 1", (guild.id,))
            if not row:
                return
            try:
                previous = json.loads(row["overwrites_json"] or "{}")
            except json.JSONDecodeError:
                previous = {}
            for channel_id, values in previous.items():
                channel = guild.get_channel(int(channel_id))
                if not isinstance(channel, discord.TextChannel):
                    continue
                overwrite = discord.PermissionOverwrite.from_pair(
                    discord.Permissions(int(values.get("allow") or 0)),
                    discord.Permissions(int(values.get("deny") or 0)),
                )
                try:
                    await channel.set_permissions(guild.default_role, overwrite=overwrite, reason="SentriX : fin du verrouillage anti-raid")
                except (discord.Forbidden, discord.HTTPException):
                    pass
            try:
                level = discord.VerificationLevel(int(row["previous_verification_level"] or 0))
                await guild.edit(verification_level=level, reason="SentriX : fin du verrouillage anti-raid")
            except (ValueError, discord.Forbidden, discord.HTTPException):
                pass
            await self.bot.db.execute(
                "UPDATE raid_lockdowns_v2 SET active = 0, updated_at = ? WHERE guild_id = ?",
                (now(), guild.id),
            )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        automod = self.bot.get_cog("Automod")
        if automod is None:
            return
        try:
            conf = await automod.get_automod_cached(member.guild.id)
        except Exception:
            return
        if not conf or not conf.get("antiraid"):
            return
        age_days = max(0, int((discord.utils.utcnow() - member.created_at).total_seconds() // 86400))
        self._joins[member.guild.id].append((time.time(), age_days, member.name, member.id, member.bot))
        score, details = self._raid_score(member.guild.id)
        if details["joins"] < 6 or score < 45:
            return
        await self.bot.db.execute(
            "INSERT INTO raid_events_v2 (guild_id, score, join_count, details_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (member.guild.id, score, details["joins"], json.dumps(details), now()),
        )
        if score >= 60:
            try:
                if member.guild.verification_level != discord.VerificationLevel.highest:
                    await member.guild.edit(verification_level=discord.VerificationLevel.highest, reason="SentriX : risque de raid élevé")
            except (discord.Forbidden, discord.HTTPException):
                pass
        if score >= 80 and details["joins"] >= 10:
            await self.activate_raid_lockdown(member.guild, seconds=600)
            self._joins[member.guild.id].clear()

    @tasks.loop(minutes=1)
    async def maintenance_loop(self):
        now_ts = int(time.time())
        rows = await self.bot.db.fetchall(
            "SELECT guild_id FROM raid_lockdowns_v2 WHERE active = 1 AND expires_at <= ?",
            (now_ts,),
        )
        for row in rows:
            guild = self.bot.get_guild(int(row["guild_id"]))
            if guild:
                await self.restore_raid_lockdown(guild)

        self._component_tick += 1
        if self._component_tick % 10 == 0:
            for guild in list(self.bot.guilds):
                try:
                    await self.run_diagnostics(guild, deep=False)
                except Exception as exc:
                    await self.record_runtime_error(guild.id, "diagnostics", exc)

    @maintenance_loop.before_loop
    async def before_maintenance_loop(self):
        try:
            await self.bot.wait_until_ready()
        except RuntimeError:
            return


async def install(bot: commands.Bot) -> OperationsCenter:
    """Installe la couche sans dupliquer les checks/listeners lors des rechargements."""
    service = bot.get_cog(_COG_NAME)
    if service is None:
        await _ensure_tables(bot)
        service = OperationsCenter(bot)
        await bot.add_cog(service)
        bot.sentrix_operations = service

    if not getattr(bot, "_sentrix_module_role_check", False):
        bot.add_check(service.module_permission_check)
        bot._sentrix_module_role_check = True

    service.attach_automod_scope()

    if not getattr(bot, "_sentrix_tree_error_audit", False):
        original = bot.tree.on_error

        async def audited_tree_error(interaction: discord.Interaction, error: BaseException):
            try:
                await service.record_runtime_error(
                    interaction.guild_id,
                    f"slash:{getattr(getattr(interaction, 'command', None), 'qualified_name', 'unknown')}",
                    getattr(error, "original", error),
                )
            finally:
                await original(interaction, error)

        bot.tree.on_error = audited_tree_error
        bot._sentrix_tree_error_audit = True

    return service
