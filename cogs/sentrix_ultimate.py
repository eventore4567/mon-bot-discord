"""SentriX Ultimate Suite — 20 systèmes professionnels isolés.

Cette extension n'altère ni le transport Discord, ni les wrappers globaux de commandes,
ni le style. Elle ajoute les systèmes avancés via un seul hub : +sentrixpro.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from typing import Any

import discord
from discord.ext import commands, tasks

import config
from database.db import now
from utils import ai_service, stats_service

logger = logging.getLogger("bot.sentrix-ultimate")

MODULES = {
    "security_center": ("Centre de sécurité", True),
    "auto_lockdown": ("Lockdown intelligent", False),
    "anti_alt": ("Anti-alt + quarantaine", False),
    "member_history": ("Historique membre", True),
    "trust_score": ("Score de confiance", True),
    "dashboard_live": ("Dashboard Live Server", True),
    "notification_center": ("Centre de notifications", True),
    "smart_welcome": ("Welcome intelligent", False),
    "smart_autorole": ("Auto-rôles intelligents", False),
    "premium_profile": ("Profil membre premium", True),
    "badges": ("Badges SentriX", True),
    "seasons": ("Saisons communautaires", True),
    "server_goals": ("Objectifs serveur", True),
    "auto_rewards": ("Récompenses automatiques", True),
    "ai_moderation": ("IA de modération", False),
    "ticket_summary": ("Résumé automatique des tickets", True),
    "staff_digest": ("Résumé quotidien staff", False),
    "status_center": ("Page statut SentriX", True),
    "module_system": ("Système de modules", True),
    "risk_events": ("Journal de risque", True),
}

BADGE_LABELS = {
    "trusted": "Trusted",
    "veteran": "Veteran",
    "active": "Active",
    "rich": "Rich",
    "staff": "Staff",
    "clean": "Clean Record",
    "season": "Season Player",
    "early": "Early Member",
}

SUSPICIOUS_WORDS = (
    "discord.gg/", "discord.com/invite/", "free nitro", "nitro gratuit",
    "steam gift", "grabber", "ip logger", "token stealer", "kys", "dox",
)

AI_MOD_INSTRUCTIONS = """Tu es un classificateur de modération Discord.
Réponds UNIQUEMENT en JSON valide, sans markdown :
{"unsafe":true|false,"confidence":0.0,"category":"harassment|threat|scam|spam|safe","reason":"phrase courte"}
Unsafe=true uniquement si le message est clairement du harcèlement sérieux, une menace,
une arnaque/phishing ou du spam agressif. Ne sanctionne pas une critique ou une blague bénigne."""


def _get(row: Any, key: str, default=None):
    try:
        value = row[key]
        return default if value is None else value
    except Exception:
        return default


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class SentriXUltimate(commands.Cog, name="SentriXUltimate"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.join_windows: dict[int, deque[float]] = defaultdict(lambda: deque(maxlen=100))
        self.voice_started: dict[tuple[int, int], float] = {}
        self.active_members: dict[int, set[int]] = defaultdict(set)
        self.ai_busy: set[int] = set()
        self.ticket_patch_installed = False

    async def cog_load(self):
        await self._tables()
        self._patch_dashboard_metrics()
        self._patch_ticket_summary()
        if not self.maintenance.is_running():
            self.maintenance.start()

    async def cog_unload(self):
        if self.maintenance.is_running():
            self.maintenance.cancel()

    async def _tables(self):
        statements = [
            "CREATE TABLE IF NOT EXISTS ultimate_modules(guild_id INTEGER NOT NULL,module TEXT NOT NULL,enabled INTEGER NOT NULL,PRIMARY KEY(guild_id,module))",
            "CREATE TABLE IF NOT EXISTS ultimate_security_events(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER NOT NULL,user_id INTEGER,event_type TEXT NOT NULL,score INTEGER NOT NULL DEFAULT 1,details TEXT,created_at INTEGER NOT NULL)",
            "CREATE TABLE IF NOT EXISTS ultimate_quarantine(guild_id INTEGER PRIMARY KEY,role_id INTEGER,channel_id INTEGER,min_account_hours INTEGER NOT NULL DEFAULT 72)",
            "CREATE TABLE IF NOT EXISTS ultimate_lockdown(guild_id INTEGER PRIMARY KEY,active INTEGER NOT NULL DEFAULT 0,until_ts INTEGER,reason TEXT,channels_json TEXT)",
            "CREATE TABLE IF NOT EXISTS ultimate_member_seen(guild_id INTEGER NOT NULL,user_id INTEGER NOT NULL,first_seen INTEGER NOT NULL,last_seen INTEGER NOT NULL,joins INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(guild_id,user_id))",
            "CREATE TABLE IF NOT EXISTS ultimate_autoroles(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER NOT NULL,metric TEXT NOT NULL,threshold INTEGER NOT NULL,role_id INTEGER NOT NULL)",
            "CREATE TABLE IF NOT EXISTS ultimate_badges(guild_id INTEGER NOT NULL,user_id INTEGER NOT NULL,badge TEXT NOT NULL,unlocked_at INTEGER NOT NULL,PRIMARY KEY(guild_id,user_id,badge))",
            "CREATE TABLE IF NOT EXISTS ultimate_goals(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER NOT NULL,metric TEXT NOT NULL,target INTEGER NOT NULL,progress INTEGER NOT NULL DEFAULT 0,reward_role_id INTEGER,reward_money INTEGER NOT NULL DEFAULT 0,starts_at INTEGER NOT NULL,ends_at INTEGER,status TEXT NOT NULL DEFAULT 'active')",
            "CREATE TABLE IF NOT EXISTS ultimate_settings(guild_id INTEGER NOT NULL,key TEXT NOT NULL,value TEXT,PRIMARY KEY(guild_id,key))",
            "CREATE TABLE IF NOT EXISTS ultimate_ticket_summaries(ticket_id INTEGER PRIMARY KEY,guild_id INTEGER NOT NULL,summary TEXT NOT NULL,created_at INTEGER NOT NULL)",
            "CREATE TABLE IF NOT EXISTS ultimate_ai_mod(guild_id INTEGER PRIMARY KEY,enabled INTEGER NOT NULL DEFAULT 0,action TEXT NOT NULL DEFAULT 'alert',confidence REAL NOT NULL DEFAULT 0.88)",
            "CREATE TABLE IF NOT EXISTS ultimate_staff_digest(guild_id INTEGER PRIMARY KEY,channel_id INTEGER NOT NULL,last_day TEXT)",
        ]
        for sql in statements:
            await self.bot.db.execute(sql)

    async def _enabled(self, guild_id: int, module: str) -> bool:
        row = await self.bot.db.fetchone(
            "SELECT enabled FROM ultimate_modules WHERE guild_id=? AND module=?",
            (guild_id, module),
        )
        if row is not None:
            return bool(int(_get(row, "enabled", 0)))
        return bool(MODULES.get(module, ("", False))[1])

    async def _set_module(self, guild_id: int, module: str, enabled: bool):
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO ultimate_modules(guild_id,module,enabled) VALUES(?,?,?)",
            (guild_id, module, int(enabled)),
        )

    async def _setting(self, guild_id: int, key: str, default: str | None = None):
        row = await self.bot.db.fetchone(
            "SELECT value FROM ultimate_settings WHERE guild_id=? AND key=?", (guild_id, key)
        )
        return str(_get(row, "value", default)) if row is not None else default

    async def _set_setting(self, guild_id: int, key: str, value: str | int | None):
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO ultimate_settings(guild_id,key,value) VALUES(?,?,?)",
            (guild_id, key, None if value is None else str(value)),
        )

    async def _event(self, guild_id: int, user_id: int | None, kind: str, score: int, details: str):
        await self.bot.db.execute(
            "INSERT INTO ultimate_security_events(guild_id,user_id,event_type,score,details,created_at) VALUES(?,?,?,?,?,?)",
            (guild_id, user_id, kind, int(score), details[:800], now()),
        )

    async def _stats(self, member: discord.Member) -> dict[str, Any]:
        try:
            return await stats_service.get_member_statistics(self.bot, member.guild, member)
        except Exception:
            return {"current_level": 0, "message_count": 0, "voice_time": 0, "wallet": 0, "bank": 0, "rank": None, "is_ranked": False}

    async def _trust(self, member: discord.Member) -> int:
        score = 50
        current = datetime.now(timezone.utc)
        account_days = max(0, (current - member.created_at).days)
        score += min(20, account_days // 30)
        if member.joined_at:
            score += min(15, max(0, (current - member.joined_at).days) // 15)
        score += min(5, max(0, len(member.roles) - 1))
        try:
            row = await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM warnings WHERE guild_id=? AND user_id=?", (member.guild.id, member.id))
            score -= min(30, int(_get(row, "n", 0)) * 8)
        except Exception:
            pass
        try:
            row = await self.bot.db.fetchone(
                "SELECT COALESCE(SUM(score),0) AS s FROM ultimate_security_events WHERE guild_id=? AND user_id=? AND created_at>=?",
                (member.guild.id, member.id, now() - 30 * 86400),
            )
            score -= min(25, int(_get(row, "s", 0)))
        except Exception:
            pass
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            score += 10
        return _clamp(score, 0, 100)

    async def _badges(self, member: discord.Member) -> list[str]:
        if not await self._enabled(member.guild.id, "badges"):
            return []
        stats = await self._stats(member)
        trust = await self._trust(member)
        guild_days = (datetime.now(timezone.utc) - member.joined_at).days if member.joined_at else 0
        wanted = set()
        if trust >= 80: wanted.add("trusted")
        if guild_days >= 180: wanted.add("veteran")
        if int(stats.get("message_count", 0)) >= 1000: wanted.add("active")
        if int(stats.get("wallet", 0)) + int(stats.get("bank", 0)) >= 10000: wanted.add("rich")
        if member.guild_permissions.manage_messages or member.guild_permissions.moderate_members: wanted.add("staff")
        try:
            row = await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM sanctions WHERE guild_id=? AND user_id=?", (member.guild.id, member.id))
            if int(_get(row, "n", 0)) == 0: wanted.add("clean")
        except Exception:
            wanted.add("clean")
        try:
            row = await self.bot.db.fetchone("SELECT season_xp FROM member_engagement WHERE guild_id=? AND user_id=?", (member.guild.id, member.id))
            if row and int(_get(row, "season_xp", 0)) > 0: wanted.add("season")
        except Exception:
            pass
        if guild_days >= 365: wanted.add("early")
        for badge in wanted:
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO ultimate_badges(guild_id,user_id,badge,unlocked_at) VALUES(?,?,?,?)",
                (member.guild.id, member.id, badge, now()),
            )
        rows = await self.bot.db.fetchall("SELECT badge FROM ultimate_badges WHERE guild_id=? AND user_id=? ORDER BY unlocked_at", (member.guild.id, member.id))
        return [str(_get(row, "badge")) for row in rows if _get(row, "badge")]

    async def _autoroles(self, member: discord.Member):
        if not await self._enabled(member.guild.id, "smart_autorole"):
            return
        rows = await self.bot.db.fetchall("SELECT metric,threshold,role_id FROM ultimate_autoroles WHERE guild_id=?", (member.guild.id,))
        stats = None
        trust = None
        for row in rows:
            metric = str(_get(row, "metric", ""))
            threshold = int(_get(row, "threshold", 0))
            role = member.guild.get_role(int(_get(row, "role_id", 0)))
            if not role or role in member.roles or role.managed:
                continue
            if metric == "days":
                value = (datetime.now(timezone.utc) - member.joined_at).days if member.joined_at else 0
            elif metric == "trust":
                trust = trust if trust is not None else await self._trust(member)
                value = trust
            else:
                stats = stats or await self._stats(member)
                value = int(stats.get("message_count" if metric == "messages" else "current_level", 0))
            if value >= threshold:
                try:
                    await member.add_roles(role, reason=f"SentriX auto-rôle: {metric}>={threshold}")
                except (discord.Forbidden, discord.HTTPException):
                    pass

    async def _goal(self, guild: discord.Guild, metric: str, amount: int, actor: discord.Member | None):
        if not await self._enabled(guild.id, "server_goals"):
            return
        rows = await self.bot.db.fetchall(
            "SELECT * FROM ultimate_goals WHERE guild_id=? AND metric=? AND status='active' AND (ends_at IS NULL OR ends_at>=?)",
            (guild.id, metric, now()),
        )
        for row in rows:
            goal_id = int(_get(row, "id"))
            target = max(1, int(_get(row, "target", 1)))
            old = int(_get(row, "progress", 0))
            new = min(target, old + int(amount))
            await self.bot.db.execute("UPDATE ultimate_goals SET progress=? WHERE id=?", (new, goal_id))
            if old < target <= new:
                await self.bot.db.execute("UPDATE ultimate_goals SET status='done' WHERE id=?", (goal_id,))
                if actor and await self._enabled(guild.id, "auto_rewards"):
                    role_id = _get(row, "reward_role_id")
                    if role_id:
                        role = guild.get_role(int(role_id))
                        if role:
                            try: await actor.add_roles(role, reason=f"Objectif SentriX #{goal_id}")
                            except (discord.Forbidden, discord.HTTPException): pass
                    money = int(_get(row, "reward_money", 0))
                    if money > 0:
                        try:
                            await self.bot.db.ensure_economy(guild.id, actor.id)
                            await self.bot.db.add_balance(guild.id, actor.id, money)
                        except Exception:
                            logger.debug("Récompense économie impossible", exc_info=True)

    async def _security(self, guild: discord.Guild) -> dict[str, Any]:
        row = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS n,COALESCE(SUM(score),0) AS s FROM ultimate_security_events WHERE guild_id=? AND created_at>=?",
            (guild.id, now() - 86400),
        )
        count, severity = int(_get(row, "n", 0)), int(_get(row, "s", 0))
        protections = sum(int(await self._enabled(guild.id, x)) for x in ("auto_lockdown", "anti_alt", "ai_moderation"))
        score = _clamp(100 - min(55, severity * 2) - (3 - protections) * 5, 0, 100)
        lock = await self.bot.db.fetchone("SELECT active,until_ts,reason FROM ultimate_lockdown WHERE guild_id=?", (guild.id,))
        return {"score": score, "events": count, "severity": severity, "protections": protections, "lockdown": bool(int(_get(lock, "active", 0))), "until": _get(lock, "until_ts"), "reason": _get(lock, "reason", "")}

    async def _start_lockdown(self, guild: discord.Guild, reason: str, duration: int = 300) -> bool:
        if not guild.me or not guild.me.guild_permissions.manage_channels:
            return False
        current = await self.bot.db.fetchone("SELECT active FROM ultimate_lockdown WHERE guild_id=?", (guild.id,))
        if current and int(_get(current, "active", 0)):
            return True
        previous = {}
        for channel in guild.text_channels:
            try:
                ow = channel.overwrites_for(guild.default_role)
                previous[str(channel.id)] = ow.send_messages
                ow.send_messages = False
                await channel.set_permissions(guild.default_role, overwrite=ow, reason=f"SentriX lockdown: {reason}")
            except (discord.Forbidden, discord.HTTPException):
                pass
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO ultimate_lockdown(guild_id,active,until_ts,reason,channels_json) VALUES(?,?,?,?,?)",
            (guild.id, 1, now() + duration, reason[:200], json.dumps(previous)),
        )
        await self._event(guild.id, None, "lockdown", 8, reason)
        return True

    async def _stop_lockdown(self, guild: discord.Guild):
        row = await self.bot.db.fetchone("SELECT channels_json FROM ultimate_lockdown WHERE guild_id=? AND active=1", (guild.id,))
        if not row: return
        try: previous = json.loads(_get(row, "channels_json", "{}") or "{}")
        except Exception: previous = {}
        for cid, old in previous.items():
            channel = guild.get_channel(int(cid))
            if isinstance(channel, discord.TextChannel):
                try:
                    ow = channel.overwrites_for(guild.default_role)
                    ow.send_messages = old
                    await channel.set_permissions(guild.default_role, overwrite=ow, reason="Fin du lockdown SentriX")
                except (discord.Forbidden, discord.HTTPException):
                    pass
        await self.bot.db.execute("UPDATE ultimate_lockdown SET active=0,until_ts=NULL,reason=NULL WHERE guild_id=?", (guild.id,))

    async def _quarantine(self, member: discord.Member, reason: str) -> bool:
        row = await self.bot.db.fetchone("SELECT role_id FROM ultimate_quarantine WHERE guild_id=?", (member.guild.id,))
        if not row: return False
        role = member.guild.get_role(int(_get(row, "role_id", 0)))
        if not role: return False
        try:
            await member.add_roles(role, reason=reason)
            await self._event(member.guild.id, member.id, "quarantine", 5, reason)
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    async def live_snapshot(self, guild: discord.Guild) -> dict[str, Any]:
        voice_users = sum(len(c.members) for c in guild.voice_channels)
        online = sum(1 for m in guild.members if not m.bot and getattr(m, "status", discord.Status.offline) != discord.Status.offline)
        try:
            row = await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM tickets WHERE guild_id=? AND status='ouvert'", (guild.id,))
            tickets = int(_get(row, "n", 0))
        except Exception: tickets = 0
        sec = await self._security(guild)
        enabled = sum(int(await self._enabled(guild.id, name)) for name in MODULES)
        return {"online_members": online, "voice_users": voice_users, "open_tickets": tickets, "security_score": sec["score"], "security_events_24h": sec["events"], "lockdown": sec["lockdown"], "modules_enabled": enabled, "modules_total": len(MODULES), "latency_ms": round(self.bot.latency * 1000)}

    def _patch_dashboard_metrics(self):
        try:
            from web import dashboard
            if getattr(dashboard, "_sentrix_ultimate_metrics", False): return
            original = dashboard._guild_metrics
            async def wrapped(db, guild_id: int):
                data = await original(db, guild_id)
                guild = self.bot.get_guild(int(guild_id))
                if guild and await self._enabled(guild.id, "dashboard_live"):
                    data["live"] = await self.live_snapshot(guild)
                return data
            dashboard._guild_metrics = wrapped
            dashboard._sentrix_ultimate_metrics = True
        except Exception:
            logger.exception("Patch Dashboard Live impossible")

    async def _ticket_summary(self, ticket_id: int, reason: str, transcript: str) -> str:
        if transcript:
            result = await ai_service.generate(
                f"Ticket #{ticket_id}\nMotif fermeture: {reason}\nTranscript:\n{transcript[-9000:]}\n\nRésume en 4 lignes: demande, actions staff, résultat, suivi.",
                model_key=ai_service.MODEL_LUNA, reasoning_effort="none",
                instructions="Tu résumes des tickets Discord. Sois factuel, bref et n'invente rien.",
                command="ticket-summary",
            )
            if result.ok and result.text: return result.text[:3500]
        return f"Ticket #{ticket_id} fermé. Motif : {reason or 'Aucune raison fournie'}."

    def _patch_ticket_summary(self):
        if self.ticket_patch_installed: return
        tickets = self.bot.get_cog("Tickets")
        if tickets is None or getattr(tickets, "_sentrix_ultimate_summary", False): return
        original = tickets.close_ticket
        async def wrapped(interaction: discord.Interaction, ticket_id: int, reason: str):
            try:
                if interaction.guild and await self._enabled(interaction.guild.id, "ticket_summary"):
                    ticket = await self.bot.db.fetchone("SELECT * FROM tickets WHERE id=?", (ticket_id,))
                    channel = interaction.guild.get_channel(int(_get(ticket, "channel_id", 0))) if ticket else None
                    transcript = ""
                    if isinstance(channel, discord.TextChannel) and hasattr(tickets, "_fetch_transcript_text"):
                        transcript = await tickets._fetch_transcript_text(channel)
                    summary = await self._ticket_summary(ticket_id, reason, transcript)
                    await self.bot.db.execute("INSERT OR REPLACE INTO ultimate_ticket_summaries(ticket_id,guild_id,summary,created_at) VALUES(?,?,?,?)", (ticket_id, interaction.guild.id, summary, now()))
                    try:
                        conf = await self.bot.db.get_guild_config(interaction.guild.id)
                        log_id = _get(conf, "ticket_log_channel")
                        log = interaction.guild.get_channel(int(log_id)) if log_id else None
                        if isinstance(log, discord.TextChannel):
                            e = discord.Embed(title=f"Résumé ticket #{ticket_id}", description=summary, colour=discord.Colour.blurple())
                            e.add_field(name="Fermeture", value=reason[:1000] or "Aucune raison", inline=False)
                            await log.send(embed=e)
                    except Exception: pass
            except Exception:
                logger.exception("Résumé ticket automatique impossible")
            return await original(interaction, ticket_id, reason)
        tickets.close_ticket = wrapped
        tickets._sentrix_ultimate_summary = True
        self.ticket_patch_installed = True

    def _suspicious(self, message: discord.Message) -> bool:
        text = (message.content or "").casefold()
        if not text: return False
        if any(x in text for x in SUSPICIOUS_WORDS): return True
        if len(message.mentions) >= 5: return True
        letters = [c for c in message.content if c.isalpha()]
        if len(letters) >= 20 and sum(c.isupper() for c in letters) / len(letters) >= 0.8: return True
        return bool(re.search(r"(.)\1{10,}", text))

    async def _security_alert(self, guild: discord.Guild, text: str, colour: int = 0xFEE75C):
        cid = await self._setting(guild.id, "security_channel")
        channel = guild.get_channel(int(cid)) if cid and cid.isdigit() else None
        if not isinstance(channel, discord.TextChannel):
            try:
                conf = await self.bot.db.get_guild_config(guild.id)
                fallback = _get(conf, "log_automod") or _get(conf, "log_channel")
                channel = guild.get_channel(int(fallback)) if fallback else None
            except Exception: channel = None
        if isinstance(channel, discord.TextChannel):
            try: await channel.send(embed=discord.Embed(description=text[:4000], colour=discord.Colour(colour)))
            except Exception: pass

    async def _ai_moderate(self, message: discord.Message):
        if message.id in self.ai_busy: return
        self.ai_busy.add(message.id)
        try:
            cfg = await self.bot.db.fetchone("SELECT enabled,action,confidence FROM ultimate_ai_mod WHERE guild_id=?", (message.guild.id,))
            enabled = bool(int(_get(cfg, "enabled", 0))) or await self._enabled(message.guild.id, "ai_moderation")
            if not enabled: return
            action, threshold = str(_get(cfg, "action", "alert")), float(_get(cfg, "confidence", 0.88))
            result = await ai_service.generate(
                message.content[:1800], model_key=ai_service.MODEL_LUNA, reasoning_effort="none",
                instructions=AI_MOD_INSTRUCTIONS, guild_id=message.guild.id, channel_id=message.channel.id,
                user_id=message.author.id, command="ai-moderation",
            )
            if not result.ok or not result.text: return
            raw = result.text.strip().removeprefix("```json").removesuffix("```").strip()
            try: data = json.loads(raw)
            except Exception: return
            if not data.get("unsafe") or float(data.get("confidence", 0)) < threshold: return
            reason = str(data.get("reason") or data.get("category") or "Contenu à risque")[:300]
            await self._event(message.guild.id, message.author.id, "ai_moderation", 4, reason)
            if action in {"delete", "timeout"}:
                try: await message.delete()
                except (discord.Forbidden, discord.HTTPException): pass
            if action == "timeout" and isinstance(message.author, discord.Member):
                try: await message.author.timeout(discord.utils.utcnow() + timedelta(minutes=10), reason=f"SentriX AI: {reason}")
                except Exception: pass
            await self._security_alert(message.guild, f"IA modération • {message.author.mention} • {reason}", 0xED4245)
        finally:
            self.ai_busy.discard(message.id)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        ts = time.time(); window = self.join_windows[member.guild.id]; window.append(ts)
        while window and ts - window[0] > 15: window.popleft()
        seen = await self.bot.db.fetchone("SELECT joins FROM ultimate_member_seen WHERE guild_id=? AND user_id=?", (member.guild.id, member.id))
        joins = int(_get(seen, "joins", 0)) + 1
        if seen:
            await self.bot.db.execute("UPDATE ultimate_member_seen SET last_seen=?,joins=? WHERE guild_id=? AND user_id=?", (now(), joins, member.guild.id, member.id))
        else:
            await self.bot.db.execute("INSERT INTO ultimate_member_seen(guild_id,user_id,first_seen,last_seen,joins) VALUES(?,?,?,?,1)", (member.guild.id, member.id, now(), now()))
        account_hours = (discord.utils.utcnow() - member.created_at).total_seconds() / 3600
        quarantined = False
        qcfg = await self.bot.db.fetchone("SELECT min_account_hours FROM ultimate_quarantine WHERE guild_id=?", (member.guild.id,))
        if qcfg and await self._enabled(member.guild.id, "anti_alt"):
            limit = int(_get(qcfg, "min_account_hours", 72))
            if account_hours < limit: quarantined = await self._quarantine(member, f"Compte récent: {account_hours:.1f}h < {limit}h")
        if await self._enabled(member.guild.id, "auto_lockdown") and len(window) >= 6:
            await self._start_lockdown(member.guild, f"Pic de {len(window)} arrivées en moins de 15 secondes")
            await self._security_alert(member.guild, f"Lockdown automatique activé : {len(window)} arrivées / 15 s.", 0xED4245)
        if await self._enabled(member.guild.id, "smart_welcome"):
            cid = await self._setting(member.guild.id, "smart_welcome_channel")
            channel = member.guild.get_channel(int(cid)) if cid and cid.isdigit() else None
            if isinstance(channel, discord.TextChannel):
                if quarantined: text = f"{member.mention}, bienvenue. Ton compte est récent : une vérification rapide est nécessaire."
                elif joins > 1: text = f"Bon retour {member.mention} sur **{member.guild.name}**."
                else: text = f"Bienvenue {member.mention} sur **{member.guild.name}** • membre #{member.guild.member_count or '?'}"
                try: await channel.send(text)
                except Exception: pass
        await self._goal(member.guild, "joins", 1, member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self.bot.db.execute("UPDATE ultimate_member_seen SET last_seen=? WHERE guild_id=? AND user_id=?", (now(), member.guild.id, member.id))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot: return
        self.active_members[message.guild.id].add(message.author.id)
        await self._goal(message.guild, "messages", 1, message.author if isinstance(message.author, discord.Member) else None)
        if self._suspicious(message): asyncio.create_task(self._ai_moderate(message))

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        key = (member.guild.id, member.id)
        if before.channel is None and after.channel is not None: self.voice_started[key] = time.time()
        elif before.channel is not None and after.channel is None:
            started = self.voice_started.pop(key, None)
            if started:
                minutes = int((time.time() - started) // 60)
                if minutes > 0: await self._goal(member.guild, "voice_minutes", minutes, member)
        elif before.channel != after.channel and after.channel is not None:
            self.voice_started.setdefault(key, time.time())

    async def _digest_embed(self, guild: discord.Guild) -> discord.Embed:
        since = now() - 86400
        async def count(query, params):
            try:
                row = await self.bot.db.fetchone(query, params); return int(_get(row, "n", 0))
            except Exception: return 0
        joins = await count("SELECT COUNT(*) AS n FROM ultimate_member_seen WHERE guild_id=? AND first_seen>=?", (guild.id, since))
        sanctions = await count("SELECT COUNT(*) AS n FROM sanctions WHERE guild_id=? AND created_at>=?", (guild.id, since))
        tickets = await count("SELECT COUNT(*) AS n FROM tickets WHERE guild_id=? AND created_at>=?", (guild.id, since))
        alerts = await count("SELECT COUNT(*) AS n FROM ultimate_security_events WHERE guild_id=? AND created_at>=?", (guild.id, since))
        open_tickets = await count("SELECT COUNT(*) AS n FROM tickets WHERE guild_id=? AND status='ouvert'", (guild.id,))
        live = await self.live_snapshot(guild)
        e = discord.Embed(title="Résumé staff — 24 dernières heures", colour=discord.Colour.blurple())
        e.description = f"Nouveaux membres : **{joins}**\nSanctions : **{sanctions}**\nTickets créés : **{tickets}** • ouverts : **{open_tickets}**\nAlertes sécurité : **{alerts}**\nScore sécurité : **{live['security_score']}/100**"
        e.set_footer(text="SentriX • Rapport automatique")
        return e

    @tasks.loop(minutes=5)
    async def maintenance(self):
        if not self.bot.is_ready(): return
        rows = await self.bot.db.fetchall("SELECT guild_id,until_ts FROM ultimate_lockdown WHERE active=1")
        for row in rows:
            if int(_get(row, "until_ts", 0) or 0) <= now():
                guild = self.bot.get_guild(int(_get(row, "guild_id", 0)))
                if guild: await self._stop_lockdown(guild)
        for gid, ids in list(self.active_members.items()):
            guild = self.bot.get_guild(gid)
            if guild:
                for uid in list(ids)[:200]:
                    member = guild.get_member(uid)
                    if member:
                        await self._autoroles(member)
                        await self._badges(member)
            ids.clear()
        if datetime.now(timezone.utc).hour == 18:
            today = _day()
            rows = await self.bot.db.fetchall("SELECT guild_id,channel_id,last_day FROM ultimate_staff_digest")
            for row in rows:
                gid = int(_get(row, "guild_id", 0))
                if _get(row, "last_day") == today or not await self._enabled(gid, "staff_digest"): continue
                guild = self.bot.get_guild(gid); channel = guild.get_channel(int(_get(row, "channel_id", 0))) if guild else None
                if isinstance(channel, discord.TextChannel):
                    try:
                        await channel.send(embed=await self._digest_embed(guild))
                        await self.bot.db.execute("UPDATE ultimate_staff_digest SET last_day=? WHERE guild_id=?", (today, gid))
                    except Exception: pass
        self._patch_ticket_summary()

    @maintenance.before_loop
    async def before_maintenance(self):
        await self.bot.wait_until_ready()

    @commands.group(name="sentrixpro", aliases=["spro"], invoke_without_command=True)
    @commands.guild_only()
    async def sentrixpro(self, ctx: commands.Context):
        e = discord.Embed(title="SentriX Pro Suite", colour=discord.Colour.blurple())
        e.description = "20 systèmes professionnels dans un seul hub.\n\n`+sentrixpro security` • sécurité\n`+sentrixpro live` • serveur en direct\n`+sentrixpro profile [membre]` • profil premium\n`+sentrixpro trust [membre]` • confiance\n`+sentrixpro history @membre` • historique\n`+sentrixpro modules` • modules\n`+sentrixpro help` • toutes les actions"
        await ctx.send(embed=e)

    @sentrixpro.command(name="help")
    async def pro_help(self, ctx: commands.Context):
        e = discord.Embed(title="SentriX Pro — actions", colour=discord.Colour.blurple())
        e.description = "**Sécurité**\n`security`, `lockdown on|off`, `quarantine-setup [heures]`, `trust [membre]`, `history @membre`, `aimod on|off [alert|delete|timeout]`\n\n**Communauté**\n`profile [membre]`, `badges [membre]`, `season [membre]`, `goal add|list|remove`, `autorole add|list|remove`\n\n**Automatisation**\n`welcome #salon|off`, `digest #salon|off`, `notifications`, `ticket-summary <id>`\n\n**Système**\n`live`, `status`, `modules`, `module enable|disable <nom>`"
        await ctx.send(embed=e)

    @sentrixpro.command(name="security")
    @commands.has_guild_permissions(manage_guild=True)
    async def pro_security(self, ctx):
        s = await self._security(ctx.guild)
        e = discord.Embed(title="Centre de sécurité", colour=discord.Colour.green() if s['score'] >= 75 else discord.Colour.orange())
        e.description = f"Score : **{s['score']}/100**\nÉvénements 24 h : **{s['events']}**\nProtections avancées : **{s['protections']}/3**\nÉtat : **{'LOCKDOWN ACTIF' if s['lockdown'] else 'Normal'}**"
        if s['reason']: e.add_field(name="Dernière raison", value=str(s['reason'])[:1000], inline=False)
        await ctx.send(embed=e)

    @sentrixpro.command(name="lockdown")
    @commands.has_guild_permissions(manage_guild=True)
    async def pro_lockdown(self, ctx, mode: str):
        if mode.casefold() == "on": return await ctx.send("Lockdown activé pour 15 minutes." if await self._start_lockdown(ctx.guild, f"Activation manuelle par {ctx.author}", 900) else "Permissions insuffisantes.")
        if mode.casefold() == "off": await self._stop_lockdown(ctx.guild); return await ctx.send("Lockdown désactivé.")
        await ctx.send("Utilise `lockdown on` ou `lockdown off`.")

    @sentrixpro.command(name="quarantine-setup")
    @commands.has_guild_permissions(manage_guild=True)
    async def pro_quarantine(self, ctx, min_account_hours: int = 72):
        hours = _clamp(min_account_hours, 1, 720); guild = ctx.guild
        role = discord.utils.get(guild.roles, name="SentriX Quarantine") or await guild.create_role(name="SentriX Quarantine", colour=discord.Colour.dark_grey(), reason="SentriX anti-alt")
        category = discord.utils.get(guild.categories, name="SENTRIX — QUARANTAINE") or await guild.create_category("SENTRIX — QUARANTAINE", reason="SentriX anti-alt")
        channel = discord.utils.get(category.text_channels, name="verification")
        if channel is None:
            channel = await guild.create_text_channel("verification", category=category, overwrites={guild.default_role: discord.PermissionOverwrite(view_channel=False), role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True), guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)}, reason="SentriX anti-alt")
        for ch in guild.channels:
            if ch.id == channel.id or isinstance(ch, discord.CategoryChannel): continue
            try:
                ow = ch.overwrites_for(role); ow.view_channel = False; await ch.set_permissions(role, overwrite=ow, reason="SentriX quarantaine")
            except Exception: pass
        await self.bot.db.execute("INSERT OR REPLACE INTO ultimate_quarantine(guild_id,role_id,channel_id,min_account_hours) VALUES(?,?,?,?)", (guild.id, role.id, channel.id, hours))
        await self._set_module(guild.id, "anti_alt", True)
        await ctx.send(f"Quarantaine prête. Comptes de moins de {hours} h -> {channel.mention}.")

    @sentrixpro.command(name="trust")
    async def pro_trust(self, ctx, member: discord.Member | None = None):
        member = member or ctx.author; score = await self._trust(member)
        e = discord.Embed(title=f"Confiance — {member.display_name}", description=f"Score SentriX : **{score}/100**\nNiveau : **{'Élevé' if score >= 80 else 'Moyen' if score >= 55 else 'Faible'}**", colour=discord.Colour.green() if score >= 80 else discord.Colour.orange()); e.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=e)

    @sentrixpro.command(name="history")
    @commands.has_guild_permissions(moderate_members=True)
    async def pro_history(self, ctx, member: discord.Member):
        sanctions = await self.bot.db.fetchall("SELECT case_number,action,reason FROM sanctions WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 8", (ctx.guild.id, member.id))
        tickets = await self.bot.db.fetchall("SELECT id,status FROM tickets WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 5", (ctx.guild.id, member.id))
        events = await self.bot.db.fetchall("SELECT event_type,score,details FROM ultimate_security_events WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 5", (ctx.guild.id, member.id))
        e = discord.Embed(title=f"Historique — {member.display_name}", colour=discord.Colour.blurple())
        if sanctions: e.add_field(name="Sanctions", value="\n".join(f"#{_get(r,'case_number','?')} • {_get(r,'action','?')} • {str(_get(r,'reason',''))[:70]}" for r in sanctions)[:1024], inline=False)
        if tickets: e.add_field(name="Tickets", value="\n".join(f"#{_get(r,'id','?')} • {_get(r,'status','?')}" for r in tickets)[:1024], inline=False)
        if events: e.add_field(name="Sécurité", value="\n".join(f"{_get(r,'event_type','?')} • risque {_get(r,'score',0)} • {str(_get(r,'details',''))[:60]}" for r in events)[:1024], inline=False)
        if not sanctions and not tickets and not events: e.description = "Aucun historique enregistré."
        await ctx.send(embed=e)

    @sentrixpro.command(name="live")
    @commands.has_guild_permissions(manage_guild=True)
    async def pro_live(self, ctx):
        d = await self.live_snapshot(ctx.guild)
        e = discord.Embed(title="Live Server", description=f"En ligne : **{d['online_members']}**\nEn vocal : **{d['voice_users']}**\nTickets ouverts : **{d['open_tickets']}**\nSécurité : **{d['security_score']}/100**\nLockdown : **{'ACTIF' if d['lockdown'] else 'inactif'}**\nModules : **{d['modules_enabled']}/{d['modules_total']}**\nLatence : **{d['latency_ms']} ms**", colour=discord.Colour.blurple())
        await ctx.send(embed=e)

    @sentrixpro.command(name="notifications")
    @commands.has_guild_permissions(manage_guild=True)
    async def pro_notifications(self, ctx):
        try: rows = await self.bot.db.fetchall("SELECT platform,COUNT(*) AS n FROM social_notifications WHERE guild_id=? AND enabled=1 GROUP BY platform", (ctx.guild.id,))
        except Exception: rows = []
        try: scheduled = int(_get(await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM sentrix_scheduled_messages WHERE guild_id=? AND status='pending'", (ctx.guild.id,)), "n", 0))
        except Exception: scheduled = 0
        welcome = await self._setting(ctx.guild.id, "smart_welcome_channel"); digest = await self.bot.db.fetchone("SELECT channel_id FROM ultimate_staff_digest WHERE guild_id=?", (ctx.guild.id,))
        e = discord.Embed(title="Centre de notifications", colour=discord.Colour.blurple()); e.add_field(name="Réseaux", value="\n".join(f"{_get(r,'platform','?')} : {_get(r,'n',0)}" for r in rows) or "Aucune surveillance sociale.", inline=False); e.add_field(name="Annonces programmées", value=str(scheduled)); e.add_field(name="Welcome", value=f"<#{welcome}>" if welcome else "Non configuré"); e.add_field(name="Digest staff", value=f"<#{_get(digest,'channel_id')}>" if digest else "Non configuré")
        await ctx.send(embed=e)

    @sentrixpro.command(name="welcome")
    @commands.has_guild_permissions(manage_guild=True)
    async def pro_welcome(self, ctx, target: str):
        if target.casefold() == "off": await self._set_module(ctx.guild.id, "smart_welcome", False); return await ctx.send("Welcome intelligent désactivé.")
        match = re.search(r"(\d{15,22})", target); channel = ctx.guild.get_channel(int(match.group(1))) if match else None
        if not isinstance(channel, discord.TextChannel): return await ctx.send("Mentionne un salon texte.")
        await self._set_setting(ctx.guild.id, "smart_welcome_channel", channel.id); await self._set_module(ctx.guild.id, "smart_welcome", True); await ctx.send(f"Welcome intelligent activé dans {channel.mention}.")

    @sentrixpro.command(name="autorole")
    @commands.has_guild_permissions(manage_roles=True)
    async def pro_autorole(self, ctx, action: str, metric: str | None = None, threshold: int | None = None, role: discord.Role | None = None):
        action = action.casefold()
        if action == "list":
            rows = await self.bot.db.fetchall("SELECT id,metric,threshold,role_id FROM ultimate_autoroles WHERE guild_id=?", (ctx.guild.id,)); text = "\n".join(f"#{_get(r,'id')} • {_get(r,'metric')} >= {_get(r,'threshold')} -> <@&{_get(r,'role_id')}>" for r in rows) or "Aucune règle."; return await ctx.send(embed=discord.Embed(title="Auto-rôles intelligents", description=text[:4000], colour=discord.Colour.blurple()))
        if action == "remove" and metric and metric.isdigit(): await self.bot.db.execute("DELETE FROM ultimate_autoroles WHERE guild_id=? AND id=?", (ctx.guild.id, int(metric))); return await ctx.send("Règle supprimée.")
        if action == "add" and metric in {"trust","messages","level","days"} and threshold is not None and role is not None:
            await self.bot.db.execute("INSERT INTO ultimate_autoroles(guild_id,metric,threshold,role_id) VALUES(?,?,?,?)", (ctx.guild.id, metric, int(threshold), role.id)); await self._set_module(ctx.guild.id, "smart_autorole", True); return await ctx.send(f"Règle ajoutée : {metric} >= {threshold} -> {role.mention}.")
        await ctx.send("Syntaxe : `autorole add trust 80 @Role`, `autorole list`, `autorole remove <id>`.")

    @sentrixpro.command(name="profile")
    async def pro_profile(self, ctx, member: discord.Member | None = None):
        member = member or ctx.author; stats = await self._stats(member); trust = await self._trust(member); badges = await self._badges(member)
        e = discord.Embed(title=f"Profil Pro — {member.display_name}", colour=discord.Colour.blurple()); e.set_thumbnail(url=member.display_avatar.url); e.add_field(name="Progression", value=f"Niveau **{stats.get('current_level',0)}**" + (f" • Rang **#{stats.get('rank')}**" if stats.get('rank') else ""), inline=False); e.add_field(name="Activité", value=f"{stats.get('message_count',0)} messages • {stats_service.format_duration(stats.get('voice_time',0))} vocal", inline=False); e.add_field(name="Économie", value=f"{int(stats.get('wallet',0))+int(stats.get('bank',0))} total"); e.add_field(name="Confiance", value=f"{trust}/100"); e.add_field(name="Badges", value=" • ".join(BADGE_LABELS.get(b,b) for b in badges) or "Aucun", inline=False)
        await ctx.send(embed=e)

    @sentrixpro.command(name="badges")
    async def pro_badges(self, ctx, member: discord.Member | None = None):
        member = member or ctx.author; badges = await self._badges(member); await ctx.send(embed=discord.Embed(title=f"Badges — {member.display_name}", description="\n".join(f"• {BADGE_LABELS.get(b,b)}" for b in badges) or "Aucun badge débloqué.", colour=discord.Colour.blurple()))

    @sentrixpro.command(name="season")
    async def pro_season(self, ctx, member: discord.Member | None = None):
        member = member or ctx.author
        try:
            from . import community_v3
            p = await community_v3.get_progression(self.bot, ctx.guild.id, member.id); text = f"Saison : **{community_v3.season_label(p['season_id'])}**\nTier : **{p['tier']}**\nNiveau : **{p['season_level']}**\nXP : **{p['season_xp']}**"
        except Exception:
            row = await self.bot.db.fetchone("SELECT season_xp FROM member_engagement WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id)); text = f"XP saison : **{_get(row,'season_xp',0)}**" if row else "Aucune progression de saison."
        await ctx.send(embed=discord.Embed(title=f"Saison — {member.display_name}", description=text, colour=discord.Colour.blurple()))

    @sentrixpro.command(name="goal")
    @commands.has_guild_permissions(manage_guild=True)
    async def pro_goal(self, ctx, action: str, metric: str | None = None, target: int | None = None, reward_money: int = 0, reward_role: discord.Role | None = None):
        action = action.casefold()
        if action == "list":
            rows = await self.bot.db.fetchall("SELECT * FROM ultimate_goals WHERE guild_id=? ORDER BY id DESC LIMIT 15", (ctx.guild.id,)); text = "\n".join(f"#{_get(r,'id')} • {_get(r,'metric')} • {_get(r,'progress')}/{_get(r,'target')} • {_get(r,'status')}" for r in rows) or "Aucun objectif."; return await ctx.send(embed=discord.Embed(title="Objectifs serveur", description=text[:4000], colour=discord.Colour.blurple()))
        if action == "remove" and metric and metric.isdigit(): await self.bot.db.execute("DELETE FROM ultimate_goals WHERE guild_id=? AND id=?", (ctx.guild.id, int(metric))); return await ctx.send("Objectif supprimé.")
        if action == "add" and metric in {"messages","joins","voice_minutes"} and target and target > 0:
            await self.bot.db.execute("INSERT INTO ultimate_goals(guild_id,metric,target,progress,reward_role_id,reward_money,starts_at,status) VALUES(?,?,?,?,?,?,?,'active')", (ctx.guild.id, metric, int(target), 0, reward_role.id if reward_role else None, max(0, int(reward_money)), now())); return await ctx.send(f"Objectif créé : **{target} {metric}**.")
        await ctx.send("Syntaxe : `goal add messages 10000 [argent] [@role]`, `goal list`, `goal remove <id>`.")

    @sentrixpro.command(name="aimod")
    @commands.has_guild_permissions(manage_guild=True)
    async def pro_aimod(self, ctx, mode: str, action: str = "alert"):
        action = action.casefold()
        if action not in {"alert","delete","timeout"}: return await ctx.send("Action : `alert`, `delete` ou `timeout`.")
        enabled = mode.casefold() in {"on","enable","1","true"}; await self.bot.db.execute("INSERT OR REPLACE INTO ultimate_ai_mod(guild_id,enabled,action,confidence) VALUES(?,?,?,0.88)", (ctx.guild.id, int(enabled), action)); await self._set_module(ctx.guild.id, "ai_moderation", enabled); await ctx.send(f"IA de modération {'activée' if enabled else 'désactivée'} • action : {action}.")

    @sentrixpro.command(name="ticket-summary")
    @commands.has_guild_permissions(manage_channels=True)
    async def pro_ticket_summary(self, ctx, ticket_id: int):
        row = await self.bot.db.fetchone("SELECT summary FROM ultimate_ticket_summaries WHERE guild_id=? AND ticket_id=?", (ctx.guild.id, ticket_id))
        if not row: return await ctx.send("Aucun résumé enregistré pour ce ticket.")
        await ctx.send(embed=discord.Embed(title=f"Résumé ticket #{ticket_id}", description=str(_get(row,'summary'))[:4000], colour=discord.Colour.blurple()))

    @sentrixpro.command(name="digest")
    @commands.has_guild_permissions(manage_guild=True)
    async def pro_digest(self, ctx, target: str):
        if target.casefold() == "off": await self.bot.db.execute("DELETE FROM ultimate_staff_digest WHERE guild_id=?", (ctx.guild.id,)); await self._set_module(ctx.guild.id, "staff_digest", False); return await ctx.send("Résumé quotidien staff désactivé.")
        match = re.search(r"(\d{15,22})", target); channel = ctx.guild.get_channel(int(match.group(1))) if match else None
        if not isinstance(channel, discord.TextChannel): return await ctx.send("Mentionne un salon texte.")
        await self.bot.db.execute("INSERT OR REPLACE INTO ultimate_staff_digest(guild_id,channel_id,last_day) VALUES(?,?,NULL)", (ctx.guild.id, channel.id)); await self._set_module(ctx.guild.id, "staff_digest", True); await ctx.send(f"Résumé staff activé dans {channel.mention} vers 18:00 UTC.")

    @sentrixpro.command(name="status")
    async def pro_status(self, ctx):
        db_ok = True
        try: await self.bot.db.fetchone("SELECT 1 AS ok")
        except Exception: db_ok = False
        live = await self.live_snapshot(ctx.guild); ai_ok = bool(getattr(config, "OPENAI_API_KEY", None))
        e = discord.Embed(title="Statut SentriX", colour=discord.Colour.green() if db_ok and self.bot.is_ready() else discord.Colour.orange()); e.description = f"Discord : **{'OPÉRATIONNEL' if self.bot.is_ready() else 'DÉGRADÉ'}**\nBase : **{'OPÉRATIONNELLE' if db_ok else 'DÉGRADÉE'}**\nIA : **{'CONFIGURÉE' if ai_ok else 'NON CONFIGURÉE'}**\nDashboard : **ACTIF**\nLatence : **{live['latency_ms']} ms**"
        await ctx.send(embed=e)

    @sentrixpro.command(name="modules")
    @commands.has_guild_permissions(manage_guild=True)
    async def pro_modules(self, ctx):
        lines = [f"{'●' if await self._enabled(ctx.guild.id, key) else '○'} `{key}` — {label}" for key, (label, _) in MODULES.items()]
        await ctx.send(embed=discord.Embed(title="Modules SentriX", description="\n".join(lines)[:4000], colour=discord.Colour.blurple()))

    @sentrixpro.command(name="module")
    @commands.has_guild_permissions(manage_guild=True)
    async def pro_module(self, ctx, action: str, module: str):
        module = module.casefold(); action = action.casefold()
        if module not in MODULES: return await ctx.send("Module inconnu. Utilise `+sentrixpro modules`.")
        if action not in {"enable","on","1","true","disable","off","0","false"}: return await ctx.send("Utilise `module enable <nom>` ou `module disable <nom>`.")
        enabled = action in {"enable","on","1","true"}; await self._set_module(ctx.guild.id, module, enabled); await ctx.send(f"Module **{MODULES[module][0]}** {'activé' if enabled else 'désactivé'}.")


async def setup(bot: commands.Bot):
    await bot.add_cog(SentriXUltimate(bot))
