"""SentriX Enterprise Suite.

Ajoute les briques qui complètent le centre Operations sans multiplier les commandes :
- recours de bannissement avec lien privé et revue staff ;
- modmail DM <-> thread staff/dashboard ;
- monitoring runtime et métriques inter-shards ;
- sauvegarde catastrophe locale/S3 et restauration contrôlée ;
- canary runtime ;
- automatisations sûres ;
- statistiques d'activité et recommandations ;
- permissions dashboard par section ;
- PostgreSQL/Redis optionnels via utils.enterprise_infra.
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import logging
import os
import re
import resource
import secrets
import shutil
import time
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands, tasks

import config
from database.db import now
from utils.enterprise_infra import EnterpriseInfra

logger = logging.getLogger("bot.enterprise")
_COG_NAME = "EnterpriseSuite"

try:
    import boto3  # type: ignore
except Exception:  # pragma: no cover
    boto3 = None

DASHBOARD_SECTIONS = {
    "appeals": "Recours",
    "modmail": "Modmail",
    "automations": "Automatisations",
    "monitoring": "Monitoring",
    "backups": "Sauvegardes",
    "analytics": "Statistiques",
    "permissions": "Permissions dashboard",
}

ENTERPRISE_SCHEMA = """
CREATE TABLE IF NOT EXISTS enterprise_guild_settings (
    guild_id INTEGER PRIMARY KEY,
    appeals_enabled INTEGER NOT NULL DEFAULT 1,
    modmail_enabled INTEGER NOT NULL DEFAULT 1,
    modmail_channel_id INTEGER,
    automations_enabled INTEGER NOT NULL DEFAULT 1,
    external_backups_enabled INTEGER NOT NULL DEFAULT 1,
    updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ban_appeals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    ban_reason TEXT,
    case_number INTEGER,
    reviewer_id INTEGER,
    staff_note TEXT,
    created_at INTEGER NOT NULL,
    submitted_at INTEGER,
    reviewed_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ban_appeals_guild_status ON ban_appeals (guild_id, status, created_at DESC);
CREATE TABLE IF NOT EXISTS ban_appeal_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    appeal_id INTEGER NOT NULL,
    author_type TEXT NOT NULL,
    author_id INTEGER,
    content TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ban_appeal_messages_appeal ON ban_appeal_messages (appeal_id, created_at);
CREATE TABLE IF NOT EXISTS modmail_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    channel_id INTEGER,
    thread_id INTEGER,
    assigned_to INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    closed_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_modmail_threads_guild_status ON modmail_threads (guild_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_modmail_threads_thread ON modmail_threads (thread_id);
CREATE TABLE IF NOT EXISTS modmail_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_record_id INTEGER NOT NULL,
    direction TEXT NOT NULL,
    author_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    attachments_json TEXT NOT NULL DEFAULT '[]',
    discord_message_id INTEGER,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_modmail_messages_thread ON modmail_messages (thread_record_id, created_at);
CREATE TABLE IF NOT EXISTS modmail_sessions (
    user_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS automation_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    conditions_json TEXT NOT NULL DEFAULT '{}',
    actions_json TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    cooldown_seconds INTEGER NOT NULL DEFAULT 300,
    last_run_at INTEGER,
    created_by INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_automation_rules_guild_trigger ON automation_rules (guild_id, trigger_type, enabled);
CREATE TABLE IF NOT EXISTS automation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    subject_id INTEGER,
    status TEXT NOT NULL,
    details TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_automation_runs_guild_time ON automation_runs (guild_id, created_at DESC);
CREATE TABLE IF NOT EXISTS runtime_metrics_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    shard_id INTEGER,
    latency_ms REAL,
    guild_count INTEGER NOT NULL DEFAULT 0,
    member_count INTEGER NOT NULL DEFAULT 0,
    commands_minute INTEGER NOT NULL DEFAULT 0,
    errors_minute INTEGER NOT NULL DEFAULT 0,
    ram_mb REAL NOT NULL DEFAULT 0,
    db_size_mb REAL NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runtime_metrics_v2_time ON runtime_metrics_v2 (created_at DESC);
CREATE TABLE IF NOT EXISTS message_activity_hourly (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    hour_bucket INTEGER NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, channel_id, hour_bucket)
);
CREATE INDEX IF NOT EXISTS idx_message_activity_hourly_guild_time ON message_activity_hourly (guild_id, hour_bucket DESC);
CREATE TABLE IF NOT EXISTS server_stat_snapshots_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    member_count INTEGER NOT NULL,
    joins_24h INTEGER NOT NULL,
    leaves_24h INTEGER NOT NULL,
    tickets_open INTEGER NOT NULL,
    tickets_created_24h INTEGER NOT NULL,
    tickets_closed_24h INTEGER NOT NULL,
    sanctions_24h INTEGER NOT NULL,
    automod_24h INTEGER NOT NULL,
    commands_24h INTEGER NOT NULL,
    avg_ticket_resolution_seconds REAL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_server_stat_snapshots_v2_guild_time ON server_stat_snapshots_v2 (guild_id, created_at DESC);
CREATE TABLE IF NOT EXISTS sentrix_recommendations_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    recommendation_key TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE (guild_id, recommendation_key)
);
CREATE INDEX IF NOT EXISTS idx_sentrix_recommendations_v2_guild ON sentrix_recommendations_v2 (guild_id, active, severity);
CREATE TABLE IF NOT EXISTS dashboard_section_roles (
    guild_id INTEGER NOT NULL,
    section TEXT NOT NULL,
    role_id INTEGER NOT NULL,
    granted_by INTEGER,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, section, role_id)
);
CREATE TABLE IF NOT EXISTS external_backups_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    storage TEXT NOT NULL,
    location TEXT NOT NULL,
    checksum TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_by INTEGER,
    created_at INTEGER NOT NULL,
    restored_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_external_backups_v2_time ON external_backups_v2 (created_at DESC);
CREATE TABLE IF NOT EXISTS canary_checks_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    status TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);
"""


async def _ensure_tables(bot: commands.Bot) -> None:
    # aiosqlite n'expose pas executescript via Database ; on découpe uniquement sur les
    # séparateurs de fin de statement de ce schéma contrôlé.
    for statement in ENTERPRISE_SCHEMA.split(";"):
        sql = statement.strip()
        if sql:
            await bot.db.execute(sql)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (TypeError, json.JSONDecodeError):
        return default


def _hour_bucket(ts: int | None = None) -> int:
    value = int(ts or time.time())
    return value - value % 3600


class ModmailGuildSelect(discord.ui.Select):
    def __init__(self, service: "EnterpriseSuite", user_id: int, guilds: list[discord.Guild]):
        self.service = service
        self.user_id = user_id
        options = [
            discord.SelectOption(label=guild.name[:100], value=str(guild.id), description=f"ID {guild.id}"[:100])
            for guild in guilds[:25]
        ]
        super().__init__(placeholder="Choisir le serveur", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return
        guild_id = int(self.values[0])
        await self.service.select_modmail_guild(self.user_id, guild_id)
        await interaction.response.edit_message(
            content="Serveur sélectionné. Envoyez maintenant votre message à SentriX en MP.",
            view=None,
        )


class ModmailGuildView(discord.ui.View):
    def __init__(self, service: "EnterpriseSuite", user_id: int, guilds: list[discord.Guild]):
        super().__init__(timeout=300)
        self.add_item(ModmailGuildSelect(service, user_id, guilds))


class EnterpriseSuite(commands.Cog, name=_COG_NAME):
    def __init__(self, bot: commands.Bot, infra: EnterpriseInfra):
        self.bot = bot
        self.infra = infra
        self._command_count = 0
        self._error_count = 0
        self._message_counters: dict[tuple[int, int, int], int] = defaultdict(int)
        self._backup_lock = asyncio.Lock()
        self._automation_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._canary_ran = False
        self.metrics_loop.start()
        self.automation_loop.start()
        self.analytics_loop.start()
        self.backup_loop.start()

    def cog_unload(self):
        for loop in (self.metrics_loop, self.automation_loop, self.analytics_loop, self.backup_loop):
            loop.cancel()
        try:
            asyncio.create_task(self.infra.close())
        except RuntimeError:
            pass

    # ----------------------------------------------------------- settings / permissions
    async def ensure_settings(self, guild_id: int) -> None:
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO enterprise_guild_settings (guild_id, updated_at) VALUES (?, ?)",
            (guild_id, now()),
        )

    async def get_settings(self, guild_id: int) -> dict[str, Any]:
        await self.ensure_settings(guild_id)
        row = await self.bot.db.fetchone("SELECT * FROM enterprise_guild_settings WHERE guild_id = ?", (guild_id,))
        return dict(row) if row else {}

    async def update_settings(self, guild_id: int, **values: Any) -> dict[str, Any]:
        allowed = {"appeals_enabled", "modmail_enabled", "modmail_channel_id", "automations_enabled", "external_backups_enabled"}
        clean = {k: v for k, v in values.items() if k in allowed}
        if not clean:
            return await self.get_settings(guild_id)
        await self.ensure_settings(guild_id)
        parts, params = [], []
        for key, value in clean.items():
            parts.append(f"{key} = ?")
            params.append(value)
        parts.append("updated_at = ?")
        params.extend([now(), guild_id])
        await self.bot.db.execute(f"UPDATE enterprise_guild_settings SET {', '.join(parts)} WHERE guild_id = ?", tuple(params))
        return await self.get_settings(guild_id)

    async def get_dashboard_roles(self, guild_id: int) -> dict[str, list[int]]:
        rows = await self.bot.db.fetchall(
            "SELECT section, role_id FROM dashboard_section_roles WHERE guild_id = ? ORDER BY section, role_id",
            (guild_id,),
        )
        result: dict[str, list[int]] = {key: [] for key in DASHBOARD_SECTIONS}
        for row in rows:
            result.setdefault(str(row["section"]), []).append(int(row["role_id"]))
        return result

    async def set_dashboard_role(self, guild_id: int, section: str, role_id: int, enabled: bool, actor_id: int) -> None:
        section = str(section).casefold()
        if section not in DASHBOARD_SECTIONS:
            raise ValueError("Section dashboard inconnue.")
        if enabled:
            await self.bot.db.execute(
                "INSERT OR REPLACE INTO dashboard_section_roles (guild_id, section, role_id, granted_by, created_at) VALUES (?, ?, ?, ?, ?)",
                (guild_id, section, int(role_id), actor_id, now()),
            )
        else:
            await self.bot.db.execute(
                "DELETE FROM dashboard_section_roles WHERE guild_id = ? AND section = ? AND role_id = ?",
                (guild_id, section, int(role_id)),
            )

    async def dashboard_access(self, guild: discord.Guild, user_id: int, section: str) -> bool:
        member = guild.get_member(int(user_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(user_id))
            except discord.HTTPException:
                return False
        if member.id == guild.owner_id or member.guild_permissions.administrator:
            return True
        rows = await self.bot.db.fetchall(
            "SELECT role_id FROM dashboard_section_roles WHERE guild_id = ? AND section = ?",
            (guild.id, str(section).casefold()),
        )
        # Aucune règle spécifique = comportement historique du dashboard.
        if not rows:
            return True
        allowed = {int(r["role_id"]) for r in rows}
        return any(role.id in allowed for role in member.roles)

    # ----------------------------------------------------------- appeals
    async def _latest_ban_case(self, guild_id: int, user_id: int) -> tuple[int | None, str]:
        row = await self.bot.db.fetchone(
            "SELECT case_number, reason FROM sanctions WHERE guild_id = ? AND user_id = ? AND action IN ('ban','tempban') ORDER BY created_at DESC LIMIT 1",
            (guild_id, user_id),
        )
        if not row:
            return None, "Aucune raison fournie"
        return int(row["case_number"]) if row["case_number"] is not None else None, str(row["reason"] or "Aucune raison fournie")

    async def create_appeal_for_ban(self, guild: discord.Guild, user: discord.User | discord.Member) -> dict[str, Any] | None:
        settings = await self.get_settings(guild.id)
        if not int(settings.get("appeals_enabled", 1)):
            return None
        await self.bot.db.execute(
            "UPDATE ban_appeals SET status='superseded', reviewed_at=? WHERE guild_id=? AND user_id=? AND status IN ('awaiting_user','open','more_info')",
            (now(), guild.id, user.id),
        )
        token = secrets.token_urlsafe(32)
        case_number, reason = await self._latest_ban_case(guild.id, user.id)
        cur = await self.bot.db.execute(
            "INSERT INTO ban_appeals (guild_id,user_id,token_hash,status,ban_reason,case_number,created_at) VALUES (?,?,?,?,?,?,?)",
            (guild.id, user.id, _token_hash(token), "awaiting_user", reason[:1500], case_number, now()),
        )
        link = f"{config.DASHBOARD_PUBLIC_URL}/appeal/{token}"
        try:
            await user.send(
                f"Vous avez été banni de **{guild.name}**.\n"
                f"Raison : {reason[:1200]}\n\n"
                "Si vous souhaitez contester cette sanction, vous pouvez envoyer un recours privé ici :\n"
                f"{link}\n\nCe lien est personnel. Ne le partagez pas."
            )
        except (discord.Forbidden, discord.HTTPException):
            pass
        payload = {"appeal_id": int(cur.lastrowid), "user_id": user.id, "case_number": case_number}
        await self.infra.mirror_event("ban_appeal_created", guild.id, payload, now())
        return {**payload, "token": token}

    async def appeal_from_token(self, token: str) -> dict[str, Any] | None:
        row = await self.bot.db.fetchone(
            "SELECT * FROM ban_appeals WHERE token_hash = ? LIMIT 1", (_token_hash(str(token)),)
        )
        if not row:
            return None
        result = dict(row)
        guild = self.bot.get_guild(int(result["guild_id"]))
        result["guild_name"] = guild.name if guild else str(result["guild_id"])
        messages = await self.bot.db.fetchall(
            "SELECT author_type, author_id, content, created_at FROM ban_appeal_messages WHERE appeal_id = ? ORDER BY created_at",
            (int(result["id"]),),
        )
        result["messages"] = [dict(r) for r in messages]
        return result

    async def submit_appeal(self, token: str, content: str) -> dict[str, Any]:
        appeal = await self.appeal_from_token(token)
        if not appeal:
            raise ValueError("Ce lien de recours est invalide.")
        if appeal["status"] not in {"awaiting_user", "more_info"}:
            raise ValueError("Ce recours ne peut plus recevoir de réponse.")
        text = str(content or "").strip()
        if len(text) < 10 or len(text) > 4000:
            raise ValueError("Le recours doit contenir entre 10 et 4 000 caractères.")
        ts = now()
        await self.bot.db.execute(
            "INSERT INTO ban_appeal_messages (appeal_id,author_type,author_id,content,created_at) VALUES (?,?,?,?,?)",
            (appeal["id"], "member", appeal["user_id"], text, ts),
        )
        await self.bot.db.execute(
            "UPDATE ban_appeals SET status='open', submitted_at=COALESCE(submitted_at,?) WHERE id=?",
            (ts, appeal["id"]),
        )
        guild = self.bot.get_guild(int(appeal["guild_id"]))
        if guild:
            await self._notify_staff(guild, f"Nouveau recours de bannissement : utilisateur {appeal['user_id']}, dossier {appeal.get('case_number') or '-'}.")
        await self.infra.mirror_event("ban_appeal_submitted", int(appeal["guild_id"]), {"appeal_id": appeal["id"]}, ts)
        return await self.appeal_from_token(token) or appeal

    async def list_appeals(self, guild_id: int, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self.bot.db.fetchall(
            "SELECT id,user_id,status,ban_reason,case_number,reviewer_id,staff_note,created_at,submitted_at,reviewed_at FROM ban_appeals WHERE guild_id=? ORDER BY created_at DESC LIMIT ?",
            (guild_id, max(1, min(int(limit), 200))),
        )
        return [dict(r) for r in rows]

    async def review_appeal(self, guild: discord.Guild, appeal_id: int, actor_id: int, decision: str, note: str = "") -> dict[str, Any]:
        row = await self.bot.db.fetchone("SELECT * FROM ban_appeals WHERE id=? AND guild_id=?", (appeal_id, guild.id))
        if not row:
            raise ValueError("Recours introuvable.")
        appeal = dict(row)
        decision = str(decision).casefold()
        if decision not in {"accepted", "refused", "more_info"}:
            raise ValueError("Décision invalide.")
        note = str(note or "").strip()[:2000]
        user = self.bot.get_user(int(appeal["user_id"]))
        if user is None:
            try:
                user = await self.bot.fetch_user(int(appeal["user_id"]))
            except discord.HTTPException:
                user = None

        if decision == "accepted":
            try:
                await guild.unban(discord.Object(id=int(appeal["user_id"])), reason=f"Recours SentriX accepté par {actor_id}")
            except discord.NotFound:
                pass
            except (discord.Forbidden, discord.HTTPException) as exc:
                raise ValueError("SentriX n'a pas pu débannir ce membre.") from exc
            dm = f"Votre recours pour **{guild.name}** a été accepté."
        elif decision == "refused":
            dm = f"Votre recours pour **{guild.name}** a été refusé."
        else:
            token = secrets.token_urlsafe(32)
            await self.bot.db.execute("UPDATE ban_appeals SET token_hash=? WHERE id=?", (_token_hash(token), appeal_id))
            dm = f"Le staff de **{guild.name}** demande des informations supplémentaires.\n{note or 'Merci de compléter votre recours.'}\n\n{config.DASHBOARD_PUBLIC_URL}/appeal/{token}"

        ts = now()
        status = decision
        await self.bot.db.execute(
            "UPDATE ban_appeals SET status=?,reviewer_id=?,staff_note=?,reviewed_at=? WHERE id=?",
            (status, actor_id, note, ts, appeal_id),
        )
        await self.bot.db.execute(
            "INSERT INTO ban_appeal_messages (appeal_id,author_type,author_id,content,created_at) VALUES (?,?,?,?,?)",
            (appeal_id, "staff", actor_id, note or decision, ts),
        )
        if user:
            try:
                await user.send(dm)
            except (discord.Forbidden, discord.HTTPException):
                pass
        await self.infra.mirror_event("ban_appeal_reviewed", guild.id, {"appeal_id": appeal_id, "decision": decision, "actor_id": actor_id}, ts)
        return dict(await self.bot.db.fetchone("SELECT * FROM ban_appeals WHERE id=?", (appeal_id,)))

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User | discord.Member):
        try:
            await asyncio.sleep(0.5)  # laisse le journal de sanction se terminer
            await self.create_appeal_for_ban(guild, user)
        except Exception as exc:
            await self._record_error(guild.id, "appeal:on_member_ban", exc)

    # ----------------------------------------------------------- modmail
    async def select_modmail_guild(self, user_id: int, guild_id: int) -> None:
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO modmail_sessions (user_id,guild_id,expires_at) VALUES (?,?,?)",
            (user_id, guild_id, now() + 3600),
        )

    async def _mutual_modmail_guilds(self, user_id: int) -> list[discord.Guild]:
        result = []
        for guild in self.bot.guilds:
            if guild.get_member(user_id) is None:
                continue
            settings = await self.get_settings(guild.id)
            if int(settings.get("modmail_enabled", 1)):
                result.append(guild)
        return result

    async def _selected_modmail_guild(self, user_id: int, mutual: list[discord.Guild]) -> discord.Guild | None:
        if len(mutual) == 1:
            return mutual[0]
        row = await self.bot.db.fetchone("SELECT guild_id,expires_at FROM modmail_sessions WHERE user_id=?", (user_id,))
        if row and int(row["expires_at"]) >= now():
            return discord.utils.get(mutual, id=int(row["guild_id"]))
        return None

    async def _open_modmail(self, guild: discord.Guild, user: discord.User | discord.Member) -> dict[str, Any]:
        existing = await self.bot.db.fetchone(
            "SELECT * FROM modmail_threads WHERE guild_id=? AND user_id=? AND status='open' ORDER BY id DESC LIMIT 1",
            (guild.id, user.id),
        )
        if existing:
            return dict(existing)
        settings = await self.get_settings(guild.id)
        channel_id = int(settings.get("modmail_channel_id") or 0) or None
        thread_id = None
        channel = guild.get_channel(channel_id) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            try:
                thread = await channel.create_thread(
                    name=f"modmail-{user.name[:45]}-{str(user.id)[-6:]}",
                    type=discord.ChannelType.public_thread,
                    auto_archive_duration=1440,
                    reason="SentriX Modmail",
                )
                thread_id = thread.id
            except (discord.Forbidden, discord.HTTPException):
                thread_id = None
        ts = now()
        cur = await self.bot.db.execute(
            "INSERT INTO modmail_threads (guild_id,user_id,status,channel_id,thread_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (guild.id, user.id, "open", channel_id, thread_id, ts, ts),
        )
        result = dict(await self.bot.db.fetchone("SELECT * FROM modmail_threads WHERE id=?", (int(cur.lastrowid),)))
        if thread_id:
            thread = guild.get_thread(thread_id)
            if thread:
                try:
                    await thread.send(f"Nouvelle conversation Modmail avec **{user}** (`{user.id}`). Répondez directement dans ce thread.")
                except discord.HTTPException:
                    pass
        return result

    async def _save_modmail_message(self, thread_record_id: int, direction: str, author_id: int, content: str, attachments: list[str], message_id: int | None = None) -> int:
        cur = await self.bot.db.execute(
            "INSERT INTO modmail_messages (thread_record_id,direction,author_id,content,attachments_json,discord_message_id,created_at) VALUES (?,?,?,?,?,?,?)",
            (thread_record_id, direction, author_id, content[:4000], json.dumps(attachments, ensure_ascii=False), message_id, now()),
        )
        await self.bot.db.execute("UPDATE modmail_threads SET updated_at=? WHERE id=?", (now(), thread_record_id))
        return int(cur.lastrowid)

    async def _member_modmail_message(self, message: discord.Message, guild: discord.Guild) -> None:
        record = await self._open_modmail(guild, message.author)
        attachments = [a.url for a in message.attachments]
        content = message.content.strip() or "Message sans texte"
        await self._save_modmail_message(int(record["id"]), "member_to_staff", message.author.id, content, attachments, message.id)
        thread = guild.get_thread(int(record.get("thread_id") or 0))
        if thread:
            text = f"**{message.author}** (`{message.author.id}`)\n{content}"
            if attachments:
                text += "\n" + "\n".join(attachments)
            try:
                await thread.send(text[:2000], allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass
        try:
            await message.channel.send(f"Votre message a été transmis au staff de **{guild.name}**.")
        except discord.HTTPException:
            pass
        await self.infra.mirror_event("modmail_member_message", guild.id, {"thread_id": record["id"], "user_id": message.author.id}, now())

    async def modmail_staff_reply(self, guild: discord.Guild, record_id: int, actor_id: int, content: str) -> None:
        row = await self.bot.db.fetchone("SELECT * FROM modmail_threads WHERE id=? AND guild_id=?", (record_id, guild.id))
        if not row or row["status"] != "open":
            raise ValueError("Conversation Modmail introuvable ou fermée.")
        text = str(content or "").strip()
        if not text or len(text) > 4000:
            raise ValueError("La réponse doit contenir entre 1 et 4 000 caractères.")
        user = self.bot.get_user(int(row["user_id"]))
        if user is None:
            try:
                user = await self.bot.fetch_user(int(row["user_id"]))
            except discord.HTTPException as exc:
                raise ValueError("Utilisateur introuvable.") from exc
        try:
            await user.send(f"**{guild.name} / Staff**\n{text}")
        except (discord.Forbidden, discord.HTTPException) as exc:
            raise ValueError("Impossible d'envoyer un MP à cet utilisateur.") from exc
        await self._save_modmail_message(record_id, "staff_to_member", actor_id, text, [])
        thread = guild.get_thread(int(row["thread_id"] or 0))
        if thread:
            try:
                await thread.send(f"Réponse dashboard par <@{actor_id}>\n{text}", allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
            except discord.HTTPException:
                pass

    async def set_modmail_status(self, guild: discord.Guild, record_id: int, actor_id: int, status: str) -> None:
        status = str(status).casefold()
        if status not in {"open", "closed"}:
            raise ValueError("Statut Modmail invalide.")
        row = await self.bot.db.fetchone("SELECT * FROM modmail_threads WHERE id=? AND guild_id=?", (record_id, guild.id))
        if not row:
            raise ValueError("Conversation introuvable.")
        await self.bot.db.execute(
            "UPDATE modmail_threads SET status=?,assigned_to=COALESCE(assigned_to,?),updated_at=?,closed_at=? WHERE id=?",
            (status, actor_id, now(), now() if status == "closed" else None, record_id),
        )
        thread = guild.get_thread(int(row["thread_id"] or 0))
        if thread:
            try:
                await thread.edit(archived=status == "closed", locked=status == "closed", reason=f"SentriX Modmail {status}")
            except (discord.Forbidden, discord.HTTPException):
                pass

    async def list_modmail(self, guild_id: int) -> list[dict[str, Any]]:
        rows = await self.bot.db.fetchall(
            "SELECT id,user_id,status,channel_id,thread_id,assigned_to,created_at,updated_at,closed_at FROM modmail_threads WHERE guild_id=? ORDER BY (status='open') DESC, updated_at DESC LIMIT 100",
            (guild_id,),
        )
        return [dict(r) for r in rows]

    async def modmail_messages(self, guild_id: int, record_id: int) -> list[dict[str, Any]]:
        row = await self.bot.db.fetchone("SELECT id FROM modmail_threads WHERE id=? AND guild_id=?", (record_id, guild_id))
        if not row:
            raise ValueError("Conversation introuvable.")
        rows = await self.bot.db.fetchall(
            "SELECT id,direction,author_id,content,attachments_json,discord_message_id,created_at FROM modmail_messages WHERE thread_record_id=? ORDER BY created_at LIMIT 300",
            (record_id,),
        )
        return [dict(r) for r in rows]

    # ----------------------------------------------------------- automations
    async def save_automation(self, guild_id: int, actor_id: int, data: dict[str, Any]) -> int:
        name = str(data.get("name") or "Automatisation").strip()[:80]
        trigger = str(data.get("trigger_type") or "").casefold()
        if trigger not in {"member_join", "warn_threshold", "ticket_stale", "schedule"}:
            raise ValueError("Déclencheur invalide.")
        conditions = data.get("conditions") if isinstance(data.get("conditions"), dict) else {}
        actions = data.get("actions") if isinstance(data.get("actions"), list) else []
        if not actions or len(actions) > 5:
            raise ValueError("Ajoutez entre 1 et 5 actions.")
        allowed_actions = {"add_role", "send_channel", "notify_role", "timeout"}
        for action in actions:
            if not isinstance(action, dict) or action.get("type") not in allowed_actions:
                raise ValueError("Une action de l'automatisation est invalide.")
        cooldown = max(30, min(int(data.get("cooldown_seconds") or 300), 86400))
        enabled = int(bool(data.get("enabled", True)))
        rule_id = int(data.get("id") or 0)
        ts = now()
        if rule_id:
            exists = await self.bot.db.fetchone("SELECT id FROM automation_rules WHERE id=? AND guild_id=?", (rule_id, guild_id))
            if not exists:
                raise ValueError("Automatisation introuvable.")
            await self.bot.db.execute(
                "UPDATE automation_rules SET name=?,trigger_type=?,conditions_json=?,actions_json=?,enabled=?,cooldown_seconds=?,updated_at=? WHERE id=? AND guild_id=?",
                (name, trigger, json.dumps(conditions, ensure_ascii=False), json.dumps(actions, ensure_ascii=False), enabled, cooldown, ts, rule_id, guild_id),
            )
            return rule_id
        cur = await self.bot.db.execute(
            "INSERT INTO automation_rules (guild_id,name,trigger_type,conditions_json,actions_json,enabled,cooldown_seconds,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (guild_id, name, trigger, json.dumps(conditions, ensure_ascii=False), json.dumps(actions, ensure_ascii=False), enabled, cooldown, actor_id, ts, ts),
        )
        return int(cur.lastrowid)

    async def list_automations(self, guild_id: int) -> list[dict[str, Any]]:
        rows = await self.bot.db.fetchall("SELECT * FROM automation_rules WHERE guild_id=? ORDER BY id DESC", (guild_id,))
        result = []
        for row in rows:
            item = dict(row)
            item["conditions"] = _json(item.pop("conditions_json", "{}"), {})
            item["actions"] = _json(item.pop("actions_json", "[]"), [])
            result.append(item)
        return result

    async def delete_automation(self, guild_id: int, rule_id: int) -> None:
        await self.bot.db.execute("DELETE FROM automation_rules WHERE guild_id=? AND id=?", (guild_id, rule_id))

    async def _matching_rules(self, guild_id: int, trigger: str) -> list[dict[str, Any]]:
        settings = await self.get_settings(guild_id)
        if not int(settings.get("automations_enabled", 1)):
            return []
        rows = await self.bot.db.fetchall(
            "SELECT * FROM automation_rules WHERE guild_id=? AND trigger_type=? AND enabled=1 ORDER BY id",
            (guild_id, trigger),
        )
        result = []
        for row in rows:
            item = dict(row)
            item["conditions"] = _json(item.pop("conditions_json", "{}"), {})
            item["actions"] = _json(item.pop("actions_json", "[]"), [])
            result.append(item)
        return result

    async def _execute_actions(self, guild: discord.Guild, rule: dict[str, Any], *, member: discord.Member | None = None, ticket: dict[str, Any] | None = None) -> str:
        logs = []
        for action in rule.get("actions", [])[:5]:
            kind = str(action.get("type") or "")
            if kind == "add_role" and member:
                role = guild.get_role(int(action.get("role_id") or 0))
                if role and not role.managed and guild.me and role < guild.me.top_role:
                    await member.add_roles(role, reason=f"SentriX automation #{rule['id']}")
                    logs.append(f"role:{role.id}")
            elif kind == "timeout" and member:
                minutes = max(1, min(int(action.get("minutes") or 10), 1440))
                await member.timeout(timedelta(minutes=minutes), reason=f"SentriX automation #{rule['id']}")
                logs.append(f"timeout:{minutes}")
            elif kind in {"send_channel", "notify_role"}:
                channel = guild.get_channel(int(action.get("channel_id") or 0))
                if not isinstance(channel, discord.TextChannel):
                    continue
                content = str(action.get("content") or "Action automatique SentriX")[:1500]
                replacements = {
                    "{member}": member.mention if member else "",
                    "{member_id}": str(member.id) if member else "",
                    "{server}": guild.name,
                    "{ticket_id}": str(ticket.get("id")) if ticket else "",
                }
                for key, value in replacements.items():
                    content = content.replace(key, value)
                allowed = discord.AllowedMentions.none()
                if kind == "notify_role":
                    role = guild.get_role(int(action.get("role_id") or 0))
                    if role:
                        content = f"{role.mention} {content}"
                        allowed = discord.AllowedMentions(roles=[role], users=False, everyone=False)
                await channel.send(content, allowed_mentions=allowed)
                logs.append(f"channel:{channel.id}")
        return ",".join(logs) or "no_action"

    async def _run_rule(self, guild: discord.Guild, rule: dict[str, Any], *, member: discord.Member | None = None, ticket: dict[str, Any] | None = None) -> bool:
        async with self._automation_locks[int(rule["id"])]:
            last = int(rule.get("last_run_at") or 0)
            if now() - last < int(rule.get("cooldown_seconds") or 300):
                return False
            try:
                details = await self._execute_actions(guild, rule, member=member, ticket=ticket)
                status = "success"
            except (discord.Forbidden, discord.HTTPException, ValueError) as exc:
                details = f"{type(exc).__name__}: {exc}"[:1000]
                status = "failure"
            ts = now()
            await self.bot.db.execute("UPDATE automation_rules SET last_run_at=? WHERE id=?", (ts, rule["id"]))
            await self.bot.db.execute(
                "INSERT INTO automation_runs (rule_id,guild_id,subject_id,status,details,created_at) VALUES (?,?,?,?,?,?)",
                (rule["id"], guild.id, member.id if member else (ticket or {}).get("user_id"), status, details, ts),
            )
            await self.infra.mirror_event("automation_run", guild.id, {"rule_id": rule["id"], "status": status}, ts)
            return status == "success"

    def _member_conditions(self, member: discord.Member, conditions: dict[str, Any]) -> bool:
        age_days = max(0, int((discord.utils.utcnow() - member.created_at).total_seconds() // 86400))
        if "account_age_days_lt" in conditions and age_days >= int(conditions["account_age_days_lt"]):
            return False
        if "account_age_days_gte" in conditions and age_days < int(conditions["account_age_days_gte"]):
            return False
        if "bots" in conditions and bool(conditions["bots"]) != bool(member.bot):
            return False
        contains = str(conditions.get("username_contains") or "").casefold()
        if contains and contains not in member.name.casefold():
            return False
        return True

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            for rule in await self._matching_rules(member.guild.id, "member_join"):
                if self._member_conditions(member, rule["conditions"]):
                    await self._run_rule(member.guild, rule, member=member)
        except Exception as exc:
            await self._record_error(member.guild.id, "automation:member_join", exc)

    # ----------------------------------------------------------- messages / modmail / activity
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.guild is not None:
            self._message_counters[(message.guild.id, message.channel.id, _hour_bucket())] += 1
            if isinstance(message.channel, discord.Thread):
                row = await self.bot.db.fetchone(
                    "SELECT * FROM modmail_threads WHERE thread_id=? AND status='open' ORDER BY id DESC LIMIT 1",
                    (message.channel.id,),
                )
                if row:
                    guild = message.guild
                    content = message.content.strip()
                    attachments = [a.url for a in message.attachments]
                    if attachments:
                        content = (content + "\n" if content else "") + "\n".join(attachments)
                    if content:
                        try:
                            await self.modmail_staff_reply(guild, int(row["id"]), message.author.id, content)
                        except ValueError:
                            pass
            return

        if not isinstance(message.channel, discord.DMChannel):
            return
        try:
            mutual = await self._mutual_modmail_guilds(message.author.id)
            if not mutual:
                return
            guild = await self._selected_modmail_guild(message.author.id, mutual)
            if guild is None:
                await message.channel.send(
                    "Vous partagez plusieurs serveurs utilisant SentriX. Choisissez le serveur concerné puis renvoyez votre message.",
                    view=ModmailGuildView(self, message.author.id, mutual),
                )
                return
            await self._member_modmail_message(message, guild)
        except Exception as exc:
            await self._record_error(None, "modmail:dm", exc)

    # ----------------------------------------------------------- monitoring / stats / suggestions
    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context):
        self._command_count += 1
        await self.infra.incr("commands:minute", 1, ttl=180)
        if not ctx.guild or not ctx.command:
            return
        root = (ctx.command.root_parent or ctx.command).name.casefold()
        if root == "warn":
            target = next((arg for arg in ctx.args if isinstance(arg, discord.Member) and arg.id != ctx.author.id), None)
            if target:
                try:
                    row = await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM warnings WHERE guild_id=? AND user_id=?", (ctx.guild.id, target.id))
                    count = int(row["n"] if row else 0)
                    for rule in await self._matching_rules(ctx.guild.id, "warn_threshold"):
                        if count >= int(rule["conditions"].get("min_warns") or 5):
                            await self._run_rule(ctx.guild, rule, member=target)
                except Exception as exc:
                    await self._record_error(ctx.guild.id, "automation:warn", exc)

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: BaseException):
        self._error_count += 1
        await self.infra.incr("errors:minute", 1, ttl=180)

    async def _record_error(self, guild_id: int | None, source: str, exc: BaseException) -> None:
        ops = self.bot.get_cog("OperationsCenter")
        if ops and hasattr(ops, "record_runtime_error"):
            try:
                await ops.record_runtime_error(guild_id, source, exc)
                return
            except Exception:
                pass
        logger.exception("Enterprise error %s: %s", source, exc)

    async def _flush_message_activity(self) -> None:
        items = list(self._message_counters.items())
        self._message_counters.clear()
        for (guild_id, channel_id, bucket), count in items:
            await self.bot.db.execute(
                "INSERT INTO message_activity_hourly (guild_id,channel_id,hour_bucket,message_count) VALUES (?,?,?,?) "
                "ON CONFLICT(guild_id,channel_id,hour_bucket) DO UPDATE SET message_count=message_count+excluded.message_count",
                (guild_id, channel_id, bucket, count),
            )

    def _ram_mb(self) -> float:
        value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # Linux = KiB, macOS = bytes.
        return round(value / (1024 if value < 10_000_000 else 1024 * 1024), 2)

    def _db_size_mb(self) -> float:
        path = Path(getattr(self.bot.db, "path", ""))
        try:
            return round(path.stat().st_size / 1024 / 1024, 2)
        except OSError:
            return 0.0

    async def monitoring_summary(self, guild_id: int | None = None) -> dict[str, Any]:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM runtime_metrics_v2 WHERE (? IS NULL OR guild_id=? OR guild_id IS NULL) ORDER BY created_at DESC LIMIT 120",
            (guild_id, guild_id),
        )
        infra = await self.infra.health()
        latencies = []
        try:
            latencies = [{"shard_id": int(sid), "latency_ms": round(float(lat) * 1000, 1)} for sid, lat in self.bot.latencies]
        except Exception:
            pass
        return {
            "current": {
                "online": self.bot.is_ready(),
                "latency_ms": round(self.bot.latency * 1000, 1) if self.bot.is_ready() else None,
                "guilds": len(self.bot.guilds),
                "members": sum(g.member_count or 0 for g in self.bot.guilds),
                "ram_mb": self._ram_mb(),
                "db_size_mb": self._db_size_mb(),
                "shard_count": int(getattr(self.bot, "shard_count", 1) or 1),
                "shards": latencies,
            },
            "infra": infra,
            "history": [dict(r) for r in rows],
            "canary": getattr(self.bot, "sentrix_canary_status", None),
        }

    async def snapshot_guild(self, guild: discord.Guild) -> dict[str, Any]:
        ts = now()
        since = ts - 86400
        async def count(sql: str, params: tuple) -> int:
            try:
                row = await self.bot.db.fetchone(sql, params)
                return int(row["n"] if row else 0)
            except Exception:
                return 0
        joins = await count("SELECT COUNT(*) AS n FROM member_invites WHERE guild_id=? AND joined_at>=?", (guild.id, since))
        leaves = await count("SELECT COUNT(*) AS n FROM member_invites WHERE guild_id=? AND left_at IS NOT NULL AND left_at>=?", (guild.id, since))
        tickets_open = await count("SELECT COUNT(*) AS n FROM tickets WHERE guild_id=? AND status='ouvert'", (guild.id,))
        tickets_created = await count("SELECT COUNT(*) AS n FROM tickets WHERE guild_id=? AND created_at>=?", (guild.id, since))
        tickets_closed = await count("SELECT COUNT(*) AS n FROM tickets WHERE guild_id=? AND closed_at IS NOT NULL AND closed_at>=?", (guild.id, since))
        sanctions = await count("SELECT COUNT(*) AS n FROM sanctions WHERE guild_id=? AND created_at>=?", (guild.id, since))
        automod = await count("SELECT COUNT(*) AS n FROM automod_logs WHERE guild_id=? AND timestamp>=?", (guild.id, since))
        commands_count = await count("SELECT COUNT(*) AS n FROM command_logs WHERE guild_id=? AND timestamp>=?", (guild.id, since))
        avg_row = await self.bot.db.fetchone(
            "SELECT AVG(closed_at-created_at) AS avg_s FROM tickets WHERE guild_id=? AND closed_at IS NOT NULL AND closed_at>=? AND closed_at>=created_at",
            (guild.id, ts - 7 * 86400),
        )
        avg_res = float(avg_row["avg_s"]) if avg_row and avg_row["avg_s"] is not None else None
        cur = await self.bot.db.execute(
            "INSERT INTO server_stat_snapshots_v2 (guild_id,member_count,joins_24h,leaves_24h,tickets_open,tickets_created_24h,tickets_closed_24h,sanctions_24h,automod_24h,commands_24h,avg_ticket_resolution_seconds,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (guild.id, guild.member_count or 0, joins, leaves, tickets_open, tickets_created, tickets_closed, sanctions, automod, commands_count, avg_res, ts),
        )
        data = {
            "id": int(cur.lastrowid), "guild_id": guild.id, "member_count": guild.member_count or 0,
            "joins_24h": joins, "leaves_24h": leaves, "tickets_open": tickets_open,
            "tickets_created_24h": tickets_created, "tickets_closed_24h": tickets_closed,
            "sanctions_24h": sanctions, "automod_24h": automod, "commands_24h": commands_count,
            "avg_ticket_resolution_seconds": avg_res, "created_at": ts,
        }
        await self.refresh_recommendations(guild, data)
        return data

    async def refresh_recommendations(self, guild: discord.Guild, stats: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        stats = stats or await self.snapshot_guild(guild)
        ts = now()
        recs: list[tuple[str, str, str, str]] = []
        joins, leaves = int(stats.get("joins_24h", 0)), int(stats.get("leaves_24h", 0))
        if leaves >= 5 and leaves > max(joins, 1) * 1.2:
            recs.append(("member_loss", "warning", "Plus de départs que d'arrivées", f"{leaves} départs contre {joins} arrivées sur les dernières 24 h. Vérifiez l'onboarding, les annonces et l'activité."))
        if int(stats.get("tickets_open", 0)) >= 10:
            recs.append(("ticket_backlog", "warning", "File de tickets importante", f"{stats['tickets_open']} tickets sont ouverts. Pensez à augmenter la disponibilité du staff ou activer une automatisation de relance."))
        avg = stats.get("avg_ticket_resolution_seconds")
        if avg and float(avg) > 7200:
            recs.append(("ticket_slow", "info", "Temps de traitement élevé", f"Le temps moyen de résolution sur 7 jours est d'environ {round(float(avg)/3600,1)} h."))
        if int(stats.get("automod_24h", 0)) >= 100:
            recs.append(("automod_volume", "warning", "Volume AutoMod élevé", f"{stats['automod_24h']} détections AutoMod en 24 h. Vérifiez les salons les plus touchés et les exceptions."))
        err = await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM runtime_errors WHERE (guild_id=? OR guild_id IS NULL) AND created_at>=?", (guild.id, ts - 86400))
        if err and int(err["n"]) >= 10:
            recs.append(("runtime_errors", "critical", "Erreurs runtime à examiner", f"{int(err['n'])} erreurs ont été enregistrées en 24 h. Consultez Monitoring avant d'ajouter de nouvelles fonctions."))
        checks = await self.bot.db.fetchall("SELECT check_name,status,details FROM component_checks WHERE guild_id=? AND status!='ok'", (guild.id,))
        if checks:
            recs.append(("diagnostics", "warning", "Diagnostic incomplet", f"{len(checks)} contrôle(s) nécessitent une vérification dans Operations."))

        await self.bot.db.execute("UPDATE sentrix_recommendations_v2 SET active=0,updated_at=? WHERE guild_id=?", (ts, guild.id))
        for key, severity, title, details in recs:
            await self.bot.db.execute(
                "INSERT INTO sentrix_recommendations_v2 (guild_id,recommendation_key,severity,title,details,active,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?) "
                "ON CONFLICT(guild_id,recommendation_key) DO UPDATE SET severity=excluded.severity,title=excluded.title,details=excluded.details,active=1,updated_at=excluded.updated_at",
                (guild.id, key, severity, title, details, ts, ts),
            )
        return await self.recommendations(guild.id)

    async def analytics(self, guild: discord.Guild) -> dict[str, Any]:
        snapshot = await self.bot.db.fetchone("SELECT * FROM server_stat_snapshots_v2 WHERE guild_id=? ORDER BY created_at DESC LIMIT 1", (guild.id,))
        if snapshot is None:
            latest = await self.snapshot_guild(guild)
        else:
            latest = dict(snapshot)
        rows = await self.bot.db.fetchall(
            "SELECT channel_id,SUM(message_count) AS messages FROM message_activity_hourly WHERE guild_id=? AND hour_bucket>=? GROUP BY channel_id ORDER BY messages DESC LIMIT 10",
            (guild.id, _hour_bucket() - 24 * 3600),
        )
        top_channels = []
        for row in rows:
            channel = guild.get_channel(int(row["channel_id"]))
            top_channels.append({"channel_id": int(row["channel_id"]), "name": channel.name if channel else str(row["channel_id"]), "messages": int(row["messages"] or 0)})
        history = await self.bot.db.fetchall("SELECT * FROM server_stat_snapshots_v2 WHERE guild_id=? ORDER BY created_at DESC LIMIT 30", (guild.id,))
        return {"latest": latest, "top_channels": top_channels, "history": [dict(r) for r in history], "recommendations": await self.recommendations(guild.id)}

    async def recommendations(self, guild_id: int) -> list[dict[str, Any]]:
        rows = await self.bot.db.fetchall(
            "SELECT recommendation_key,severity,title,details,created_at,updated_at FROM sentrix_recommendations_v2 WHERE guild_id=? AND active=1 ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, updated_at DESC",
            (guild_id,),
        )
        return [dict(r) for r in rows]

    # ----------------------------------------------------------- backups catastrophe
    def _backup_directory(self) -> Path:
        root = Path(os.getenv("SENTRIX_BACKUP_DIR", "database/backups"))
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _s3_client(self):
        bucket = os.getenv("S3_BUCKET", "").strip()
        if not bucket or boto3 is None:
            return None, None
        kwargs: dict[str, Any] = {}
        endpoint = os.getenv("S3_ENDPOINT_URL", "").strip()
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        if os.getenv("S3_ACCESS_KEY_ID"):
            kwargs["aws_access_key_id"] = os.getenv("S3_ACCESS_KEY_ID")
        if os.getenv("S3_SECRET_ACCESS_KEY"):
            kwargs["aws_secret_access_key"] = os.getenv("S3_SECRET_ACCESS_KEY")
        if os.getenv("S3_REGION"):
            kwargs["region_name"] = os.getenv("S3_REGION")
        return boto3.client("s3", **kwargs), bucket

    async def create_external_backup(self, actor_id: int | None = None) -> dict[str, Any]:
        async with self._backup_lock:
            path = Path(getattr(self.bot.db, "path", ""))
            if not path.exists():
                raise ValueError("La base SQLite active est introuvable.")
            ts = now()
            target = self._backup_directory() / f"sentrix-{ts}.db.gz"
            def compress():
                with path.open("rb") as src, gzip.open(target, "wb", compresslevel=6) as dst:
                    shutil.copyfileobj(src, dst)
            await asyncio.to_thread(compress)
            checksum = await asyncio.to_thread(lambda: hashlib.sha256(target.read_bytes()).hexdigest())
            storage, location = "local", str(target)
            client, bucket = self._s3_client()
            if client and bucket:
                key = f"sentrix/backups/{target.name}"
                try:
                    await asyncio.to_thread(client.upload_file, str(target), bucket, key)
                    storage, location = "s3", key
                except Exception as exc:
                    await self._record_error(None, "backup:s3-upload", exc)
            cur = await self.bot.db.execute(
                "INSERT INTO external_backups_v2 (storage,location,checksum,size_bytes,status,created_by,created_at) VALUES (?,?,?,?,?,?,?)",
                (storage, location, checksum, target.stat().st_size, "ready", actor_id, ts),
            )
            # Conserve au plus 12 archives locales, même quand une copie S3 existe.
            local = sorted(self._backup_directory().glob("sentrix-*.db.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in local[12:]:
                try:
                    old.unlink()
                except OSError:
                    pass
            result = {"id": int(cur.lastrowid), "storage": storage, "location": location, "checksum": checksum, "size_bytes": target.stat().st_size, "created_at": ts}
            await self.infra.mirror_event("external_backup", None, {"id": result["id"], "storage": storage, "size_bytes": result["size_bytes"]}, ts)
            return result

    async def list_external_backups(self) -> list[dict[str, Any]]:
        rows = await self.bot.db.fetchall("SELECT * FROM external_backups_v2 ORDER BY created_at DESC LIMIT 50")
        return [dict(r) for r in rows]

    async def restore_external_backup(self, backup_id: int, actor_id: int) -> None:
        async with self._backup_lock:
            row = await self.bot.db.fetchone("SELECT * FROM external_backups_v2 WHERE id=? AND status='ready'", (backup_id,))
            if not row:
                raise ValueError("Sauvegarde introuvable.")
            item = dict(row)
            temp_gz = self._backup_directory() / f"restore-{backup_id}.db.gz"
            if item["storage"] == "local":
                source = Path(item["location"])
                if not source.exists():
                    raise ValueError("Le fichier de sauvegarde local n'existe plus.")
                shutil.copy2(source, temp_gz)
            elif item["storage"] == "s3":
                client, bucket = self._s3_client()
                if not client or not bucket:
                    raise ValueError("Le stockage S3 n'est pas configuré sur ce déploiement.")
                await asyncio.to_thread(client.download_file, bucket, item["location"], str(temp_gz))
            else:
                raise ValueError("Type de stockage non supporté.")
            digest = await asyncio.to_thread(lambda: hashlib.sha256(temp_gz.read_bytes()).hexdigest())
            if digest != item["checksum"]:
                raise ValueError("Checksum invalide : restauration annulée.")
            restored = self._backup_directory() / f"restore-{backup_id}.db"
            def decompress():
                with gzip.open(temp_gz, "rb") as src, restored.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            await asyncio.to_thread(decompress)
            db_path = Path(self.bot.db.path)
            rollback = db_path.with_suffix(db_path.suffix + ".pre-restore")
            await self.bot.db.close()
            try:
                if db_path.exists():
                    shutil.copy2(db_path, rollback)
                os.replace(restored, db_path)
                await self.bot.db.connect()
                self.bot.prefix_cache.clear()
            except Exception:
                if rollback.exists():
                    os.replace(rollback, db_path)
                await self.bot.db.connect()
                raise
            finally:
                for p in (temp_gz, restored):
                    try:
                        p.unlink()
                    except OSError:
                        pass
            await self.bot.db.execute("UPDATE external_backups_v2 SET restored_at=? WHERE id=?", (now(), backup_id))
            await self.infra.mirror_event("external_backup_restored", None, {"id": backup_id, "actor_id": actor_id}, now())

    # ----------------------------------------------------------- canary
    async def run_canary(self) -> dict[str, Any]:
        guild_id = int(getattr(config, "CANARY_GUILD_ID", 0) or 0)
        details: dict[str, Any] = {"guild_id": guild_id, "checks": []}
        status = "ok"
        guild = self.bot.get_guild(guild_id) if guild_id else None
        if guild_id and guild is None:
            status = "error"
            details["checks"].append({"name": "guild", "status": "error", "details": "Serveur canary introuvable."})
        elif guild:
            ops = self.bot.get_cog("OperationsCenter")
            if ops and hasattr(ops, "run_diagnostics"):
                diag = await ops.run_diagnostics(guild, deep=True)
                details["checks"].extend(diag.get("checks", []))
                if not diag.get("ok"):
                    status = "error"
            else:
                details["checks"].append({"name": "operations", "status": "warning", "details": "OperationsCenter indisponible."})
        infra = await self.infra.health()
        details["infra"] = infra
        details["checks"].append({"name": "extensions", "status": "ok", "details": f"{len(self.bot.extensions)} extension(s) chargée(s)."})
        details["checks"].append({"name": "shards", "status": "ok", "details": f"{int(getattr(self.bot, 'shard_count', 1) or 1)} shard(s)."})
        ts = now()
        await self.bot.db.execute(
            "INSERT INTO canary_checks_v2 (guild_id,status,details_json,created_at) VALUES (?,?,?,?)",
            (guild_id or None, status, json.dumps(details, ensure_ascii=False), ts),
        )
        result = {"status": status, "created_at": ts, **details}
        self.bot.sentrix_canary_status = result
        return result

    async def canary_command_check(self, ctx: commands.Context) -> bool:
        if not getattr(config, "CANARY_MODE", False):
            return True
        guild_id = int(getattr(config, "CANARY_GUILD_ID", 0) or 0)
        if ctx.guild is not None and ctx.guild.id == guild_id:
            return True
        raise commands.CheckFailure("Ce déploiement SentriX est en mode canary.")

    @commands.Cog.listener()
    async def on_ready(self):
        if self._canary_ran:
            return
        self._canary_ran = True
        try:
            await self.run_canary()
        except Exception as exc:
            await self._record_error(None, "canary", exc)

    # ----------------------------------------------------------- helpers notification
    async def _notify_staff(self, guild: discord.Guild, content: str) -> None:
        settings = await self.get_settings(guild.id)
        channel = guild.get_channel(int(settings.get("modmail_channel_id") or 0))
        if not isinstance(channel, discord.TextChannel):
            conf = await self.bot.db.get_guild_config(guild.id)
            if conf:
                for key in ("error_channel", "log_moderation", "log_channel"):
                    try:
                        cid = conf[key]
                    except Exception:
                        cid = None
                    if cid and isinstance(guild.get_channel(int(cid)), discord.TextChannel):
                        channel = guild.get_channel(int(cid))
                        break
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(content[:2000], allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    # ----------------------------------------------------------- loops
    @tasks.loop(minutes=1)
    async def metrics_loop(self):
        try:
            await self._flush_message_activity()
            ts = now()
            commands_min = self._command_count
            errors_min = self._error_count
            self._command_count = 0
            self._error_count = 0
            redis_commands = await self.infra.get_counter("commands:minute")
            redis_errors = await self.infra.get_counter("errors:minute")
            if redis_commands is not None:
                commands_min = redis_commands
            if redis_errors is not None:
                errors_min = redis_errors
            shard_count = int(getattr(self.bot, "shard_count", 1) or 1)
            await self.bot.db.execute(
                "INSERT INTO runtime_metrics_v2 (guild_id,shard_id,latency_ms,guild_count,member_count,commands_minute,errors_minute,ram_mb,db_size_mb,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (None, None, round(self.bot.latency * 1000, 2) if self.bot.is_ready() else None, len(self.bot.guilds), sum(g.member_count or 0 for g in self.bot.guilds), commands_min, errors_min, self._ram_mb(), self._db_size_mb(), ts),
            )
            await self.infra.mirror_metric("commands_minute", None, commands_min, {"shards": shard_count}, ts)
            await self.infra.mirror_metric("latency_ms", None, self.bot.latency * 1000 if self.bot.is_ready() else 0, {"shards": shard_count}, ts)
            await self.bot.db.execute("DELETE FROM runtime_metrics_v2 WHERE created_at < ?", (ts - 14 * 86400,))
            await self.bot.db.execute("DELETE FROM message_activity_hourly WHERE hour_bucket < ?", (_hour_bucket(ts) - 30 * 86400,))
        except Exception as exc:
            await self._record_error(None, "metrics_loop", exc)

    @metrics_loop.before_loop
    async def before_metrics_loop(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def automation_loop(self):
        ts = now()
        for guild in list(self.bot.guilds):
            try:
                # Tickets sans activité.
                for rule in await self._matching_rules(guild.id, "ticket_stale"):
                    hours = max(1, min(int(rule["conditions"].get("hours") or 24), 720))
                    rows = await self.bot.db.fetchall(
                        "SELECT id,user_id,channel_id,created_at,last_activity_at,status FROM tickets WHERE guild_id=? AND status='ouvert' AND COALESCE(last_activity_at,created_at)<=? ORDER BY id LIMIT 10",
                        (guild.id, ts - hours * 3600),
                    )
                    if rows:
                        await self._run_rule(guild, rule, ticket=dict(rows[0]))
                # Planification hebdomadaire.
                current = time.gmtime(ts)
                for rule in await self._matching_rules(guild.id, "schedule"):
                    cond = rule["conditions"]
                    weekdays = cond.get("weekdays", [current.tm_wday])
                    if isinstance(weekdays, int):
                        weekdays = [weekdays]
                    hour = int(cond.get("hour", 12))
                    minute = int(cond.get("minute", 0))
                    if current.tm_wday in [int(x) for x in weekdays] and current.tm_hour == hour and abs(current.tm_min - minute) <= 4:
                        await self._run_rule(guild, rule)
            except Exception as exc:
                await self._record_error(guild.id, "automation_loop", exc)

    @automation_loop.before_loop
    async def before_automation_loop(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=1)
    async def analytics_loop(self):
        for guild in list(self.bot.guilds):
            try:
                await self.snapshot_guild(guild)
            except Exception as exc:
                await self._record_error(guild.id, "analytics_loop", exc)

    @analytics_loop.before_loop
    async def before_analytics_loop(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=6)
    async def backup_loop(self):
        try:
            # Lease Redis : un seul shard/process crée le backup partagé.
            lease = secrets.token_hex(8)
            if await self.infra.acquire_lease("external-backup", lease, ttl=1800):
                try:
                    await self.create_external_backup(None)
                finally:
                    await self.infra.release_lease("external-backup", lease)
        except Exception as exc:
            await self._record_error(None, "backup_loop", exc)

    @backup_loop.before_loop
    async def before_backup_loop(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(90)


async def setup(bot: commands.Bot) -> None:
    await _ensure_tables(bot)
    infra = getattr(bot, "sentrix_infra", None)
    if infra is None:
        infra = EnterpriseInfra()
        await infra.connect()
        bot.sentrix_infra = infra
    service = EnterpriseSuite(bot, infra)
    await bot.add_cog(service)
    bot.sentrix_enterprise = service
    if getattr(config, "CANARY_MODE", False) and not getattr(bot, "_sentrix_canary_check", False):
        bot.add_check(service.canary_command_check)
        bot._sentrix_canary_check = True
    logger.info("Enterprise Suite active : appeals, modmail, automations, monitoring, backups, canary et analytics.")
