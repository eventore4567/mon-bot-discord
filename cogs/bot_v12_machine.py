"""Bot V12 — machine suite for SentriX.

Bot-only runtime layer. It strengthens existing systems without replacing the mature
feature cogs: AI/context/memory, moderation signals, raid detection, ticket operations,
game/economy telemetry, social notification delivery, and bounded runtime maintenance.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import defaultdict, deque
from typing import Any

import discord
from discord.ext import commands, tasks

logger = logging.getLogger("bot.v12-machine")

AI_CONTEXT_TTL = 12.0
AI_CONTEXT_CACHE_MAX = 512
AI_MAX_PARALLEL = 12
AI_INFLIGHT_MAX = 256

JOIN_WINDOW_SECONDS = 20.0
JOIN_ALERT_THRESHOLD = 8
SUSPICIOUS_ACCOUNT_AGE_SECONDS = 10 * 60
SUSPICIOUS_JOIN_THRESHOLD = 3
SECURITY_ALERT_COOLDOWN = 60.0

MESSAGE_WINDOW_SECONDS = 8.0
MESSAGE_BURST_THRESHOLD = 10
MESSAGE_ALERT_COOLDOWN = 60.0

TICKET_CHECK_SECONDS = 120
TICKET_UNCLAIMED_SECONDS = 15 * 60
TICKET_REMINDER_COOLDOWN = 30 * 60

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS v12_game_form (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        wins INTEGER NOT NULL DEFAULT 0,
        losses INTEGER NOT NULL DEFAULT 0,
        current_streak INTEGER NOT NULL DEFAULT 0,
        longest_streak INTEGER NOT NULL DEFAULT 0,
        total_reward INTEGER NOT NULL DEFAULT 0,
        last_game TEXT,
        last_result TEXT,
        updated_at INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS v12_ticket_watch (
        ticket_id INTEGER PRIMARY KEY,
        guild_id INTEGER NOT NULL,
        channel_id INTEGER NOT NULL,
        last_reminder_at INTEGER NOT NULL DEFAULT 0,
        last_seen_at INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS v12_runtime_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER,
        event_type TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'info',
        actor_id INTEGER,
        target_id INTEGER,
        details_json TEXT NOT NULL DEFAULT '{}',
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_v12_runtime_events_guild_time
    ON v12_runtime_events (guild_id, created_at DESC)
    """,
)


def _row_value(row: Any, key: str, default=None):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


async def _ensure_schema(bot: commands.Bot) -> None:
    for statement in SCHEMA_STATEMENTS:
        try:
            await bot.db.execute(statement)
        except Exception:
            logger.warning("V12: création de schéma partiellement indisponible.", exc_info=True)


class BotV12Machine(commands.Cog, name="BotV12Machine"):
    """Cross-system production improvements for the existing SentriX feature set."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self._ai_context_cache: dict[tuple[int, int | None], tuple[float, str]] = {}
        self._ai_inflight: dict[str, tuple[float, asyncio.Task]] = {}
        self._ai_semaphore = asyncio.Semaphore(AI_MAX_PARALLEL)

        self._join_times: dict[int, deque[float]] = defaultdict(deque)
        self._suspicious_join_times: dict[int, deque[float]] = defaultdict(deque)
        self._message_times: dict[tuple[int, int], deque[float]] = defaultdict(deque)
        self._security_alert_at: dict[tuple[int, str], float] = {}

        self._patched_ai_context = False
        self._patched_ai_memory = False
        self._patched_ai_generate = False
        self._patched_notifications = False
        self._patched_game_rewards = False

    async def cog_load(self) -> None:
        await _ensure_schema(self.bot)
        await self.ensure_integrations()
        if not self.maintenance_loop.is_running():
            self.maintenance_loop.start()
        if not self.ticket_watch_loop.is_running():
            self.ticket_watch_loop.start()

    def cog_unload(self) -> None:
        self.maintenance_loop.cancel()
        self.ticket_watch_loop.cancel()

    async def ensure_integrations(self) -> None:
        for name, patch in (
            ("ai_context", self._patch_ai_context),
            ("ai_memory", self._patch_ai_memory),
            ("ai_generate", self._patch_ai_generate),
            ("notifications", self._patch_notifications),
            ("game_rewards", self._patch_game_reward_accounting),
        ):
            try:
                patch()
            except Exception:
                logger.warning("V12: intégration %s indisponible; nouveau cycle prévu.", name, exc_info=True)

    # ------------------------------------------------------------------ AI

    def _patch_ai_context(self) -> None:
        if self._patched_ai_context:
            return
        try:
            from . import ai_context_v9
        except Exception:
            return

        current = ai_context_v9.build_server_context
        if getattr(current, "_sentrix_v12_context_cache", False):
            self._patched_ai_context = True
            return

        async def cached_context(bot, guild_id: int | None, channel_id: int | None):
            if not guild_id:
                return await current(bot, guild_id, channel_id)
            key = (int(guild_id), int(channel_id) if channel_id else None)
            now_m = time.monotonic()
            cached = self._ai_context_cache.get(key)
            if cached and now_m - cached[0] <= AI_CONTEXT_TTL:
                return cached[1]
            value = await current(bot, guild_id, channel_id)
            if len(self._ai_context_cache) >= AI_CONTEXT_CACHE_MAX:
                oldest_key = min(self._ai_context_cache, key=lambda k: self._ai_context_cache[k][0])
                self._ai_context_cache.pop(oldest_key, None)
            self._ai_context_cache[key] = (now_m, value)
            return value

        cached_context._sentrix_v12_context_cache = True
        ai_context_v9.build_server_context = cached_context
        self._patched_ai_context = True
        logger.info("V12: cache court du contexte IA activé.")

    def _patch_ai_memory(self) -> None:
        if self._patched_ai_memory:
            return
        try:
            from utils import ai_service
        except Exception:
            return

        current = ai_service.get_conversation_history
        if getattr(current, "_sentrix_v12_latest_memory", False):
            self._patched_ai_memory = True
            return

        async def latest_history(bot, guild_id: int, channel_id: int, user_id: int, memory_minutes: int):
            cutoff = int(time.time()) - max(1, int(memory_minutes)) * 60
            try:
                rows = await bot.db.fetchall(
                    "SELECT role, content, response_id, created_at FROM ("
                    " SELECT role, content, response_id, created_at FROM ai_conversations"
                    " WHERE guild_id = ? AND channel_id = ? AND user_id = ? AND created_at >= ?"
                    " ORDER BY created_at DESC LIMIT 24"
                    ") recent ORDER BY created_at ASC",
                    (guild_id, channel_id, user_id, cutoff),
                )
            except Exception:
                logger.warning("V12: mémoire récente indisponible, repli V11/V10.", exc_info=True)
                return await current(bot, guild_id, channel_id, user_id, memory_minutes)

            if not rows:
                return [], None
            history = [
                {"role": _row_value(row, "role", "user"), "content": _row_value(row, "content", "")}
                for row in rows
            ]
            last_response_id = None
            for row in reversed(rows):
                response_id = _row_value(row, "response_id")
                if response_id:
                    last_response_id = response_id
                    break
            return history, last_response_id

        latest_history._sentrix_v12_latest_memory = True
        ai_service.get_conversation_history = latest_history
        self._patched_ai_memory = True
        logger.info("V12: mémoire IA recentrée sur les messages les plus récents.")

    def _patch_ai_generate(self) -> None:
        if self._patched_ai_generate:
            return
        try:
            from utils import ai_service
        except Exception:
            return

        current = ai_service.generate
        if getattr(current, "_sentrix_v12_deduplicated_generate", False):
            self._patched_ai_generate = True
            return

        async def generate_v12(*args, **kwargs):
            prompt = args[0] if args else kwargs.get("prompt", "")
            raw = repr(prompt)
            fingerprint_payload = "|".join(
                (
                    str(kwargs.get("guild_id") or 0),
                    str(kwargs.get("channel_id") or 0),
                    str(kwargs.get("user_id") or 0),
                    str(kwargs.get("command") or ""),
                    str(kwargs.get("model_key") or ""),
                    str(kwargs.get("reasoning_effort") or ""),
                    str(bool(kwargs.get("web_search"))),
                    str(kwargs.get("previous_response_id") or ""),
                    str(kwargs.get("instructions") or "")[:1200],
                    raw[:6000],
                )
            )
            key = hashlib.sha256(fingerprint_payload.encode("utf-8", "ignore")).hexdigest()
            existing = self._ai_inflight.get(key)
            if existing and not existing[1].done():
                return await asyncio.shield(existing[1])

            async def runner():
                async with self._ai_semaphore:
                    return await current(*args, **kwargs)

            task = asyncio.create_task(runner())
            self._ai_inflight[key] = (time.monotonic(), task)
            try:
                return await asyncio.shield(task)
            finally:
                saved = self._ai_inflight.get(key)
                if saved and saved[1] is task:
                    self._ai_inflight.pop(key, None)

        generate_v12._sentrix_v12_deduplicated_generate = True
        ai_service.generate = generate_v12
        self._patched_ai_generate = True
        logger.info("V12: déduplication IA et limite de parallélisme activées.")

    # ---------------------------------------------------------- Notifications

    def _patch_notifications(self) -> None:
        if self._patched_notifications:
            return
        service = self.bot.get_cog("Notifications")
        if service is None:
            return

        cls = type(service)
        current = cls._check_subscription
        if getattr(current, "_sentrix_v12_delivery_safe", False):
            self._patched_notifications = True
            return

        async def delivery_safe(instance, row):
            from . import notifications as n

            guild = instance.bot.get_guild(row["guild_id"])
            if guild is None:
                return
            channel = guild.get_channel(row["discord_channel_id"])
            role = guild.get_role(row["role_id"])
            if channel is None or role is None:
                try:
                    await instance.bot.db.execute(
                        "UPDATE social_notifications SET enabled = 0 WHERE id = ?",
                        (row["id"],),
                    )
                except Exception:
                    logger.warning("V12: impossible de désactiver une notification orpheline.", exc_info=True)
                return

            try:
                item = await n._extract_latest(row["source_url"])
            except Exception:
                logger.warning("V12: lecture sociale impossible id=%s", row["id"], exc_info=True)
                return
            if not item:
                return

            item_id = str(item.get("id") or "")
            if not item_id:
                return
            if not row["last_item_id"]:
                await instance._update_last_item(row["id"], item_id, row["source_url"])
                return
            if item_id == str(row["last_item_id"]):
                return

            platform = row["platform"]
            link = n._item_url(platform, row["source_url"], item)
            title = (item.get("title") or f"Nouvelle publication sur {platform}")[:256]
            description = row["custom_text"] or "Une nouvelle publication vient d'être mise en ligne."
            embed = discord.Embed(
                title=title,
                description=description,
                color=n._platform_details(row["source_url"])[1],
            )
            embed.add_field(name="Voir la publication", value=f"[Ouvrir sur {platform}]({link})", inline=False)
            embed.set_footer(text=f"Notification automatique SentriX • {platform}")
            image_url = row["image_url"] or item.get("thumbnail")
            if image_url and n._valid_https_url(image_url):
                embed.set_image(url=image_url)

            try:
                await channel.send(
                    content=role.mention,
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False,
                        users=False,
                        roles=[role],
                        replied_user=False,
                    ),
                )
            except discord.HTTPException:
                # Crucial V12: ne jamais consommer la publication si Discord n'a pas reçu le message.
                logger.warning("V12: notification non livrée, nouvel essai au prochain cycle id=%s", row["id"], exc_info=True)
                return
            except Exception:
                logger.warning("V12: erreur d'envoi notification id=%s", row["id"], exc_info=True)
                return

            try:
                await instance._update_last_item(row["id"], item_id, link)
            except Exception:
                # Le message a été livré. Une panne DB peut provoquer un doublon au prochain cycle,
                # ce qui est préférable à perdre définitivement une notification.
                logger.warning("V12: notification livrée mais checkpoint DB indisponible id=%s", row["id"], exc_info=True)

        delivery_safe._sentrix_v12_delivery_safe = True
        cls._check_subscription = delivery_safe
        self._patched_notifications = True
        logger.info("V12: livraison sociale anti-perte activée.")

    # --------------------------------------------------------------- Economy

    def _patch_game_reward_accounting(self) -> None:
        if self._patched_game_rewards:
            return
        current = getattr(self.bot.db, "record_game_reward", None)
        if not callable(current):
            return
        if getattr(current, "_sentrix_v12_game_form", False):
            self._patched_game_rewards = True
            return

        async def record_with_form(
            guild_id: int,
            user_id: int,
            game_name: str,
            session_id: str,
            result: str,
            amount: int,
            metadata_json: str,
        ):
            response = await current(
                guild_id, user_id, game_name, session_id, result, amount, metadata_json
            )
            try:
                ok = bool(response[0])
                if not ok:
                    return response
                credited = int(response[2] or 0)
                row = await self.bot.db.fetchone(
                    "SELECT wins, losses, current_streak, longest_streak, total_reward "
                    "FROM v12_game_form WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
                wins = int(_row_value(row, "wins", 0) or 0)
                losses = int(_row_value(row, "losses", 0) or 0)
                streak = int(_row_value(row, "current_streak", 0) or 0)
                longest = int(_row_value(row, "longest_streak", 0) or 0)
                total_reward = int(_row_value(row, "total_reward", 0) or 0)

                if str(result).casefold() == "win":
                    wins += 1
                    streak += 1
                    longest = max(longest, streak)
                else:
                    losses += 1
                    streak = 0
                total_reward += max(0, credited)

                await self.bot.db.execute(
                    "INSERT INTO v12_game_form "
                    "(guild_id,user_id,wins,losses,current_streak,longest_streak,total_reward,last_game,last_result,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(guild_id,user_id) DO UPDATE SET "
                    "wins=excluded.wins,losses=excluded.losses,current_streak=excluded.current_streak,"
                    "longest_streak=excluded.longest_streak,total_reward=excluded.total_reward,"
                    "last_game=excluded.last_game,last_result=excluded.last_result,updated_at=excluded.updated_at",
                    (
                        guild_id, user_id, wins, losses, streak, longest, total_reward,
                        str(game_name)[:80], str(result)[:30], int(time.time()),
                    ),
                )
            except Exception:
                # Les stats V12 ne doivent jamais empêcher le crédit monétaire principal.
                logger.warning("V12: statistiques de jeu secondaires indisponibles.", exc_info=True)
            return response

        record_with_form._sentrix_v12_game_form = True
        try:
            self.bot.db.record_game_reward = record_with_form
        except Exception:
            logger.warning("V12: impossible d'attacher les statistiques de jeu.", exc_info=True)
            return
        self._patched_game_rewards = True
        logger.info("V12: forme joueur jeux/économie activée sans modifier les récompenses.")

    # ------------------------------------------------------- Security signals

    async def _record_event(
        self,
        guild_id: int | None,
        event_type: str,
        severity: str,
        *,
        actor_id: int | None = None,
        target_id: int | None = None,
        details: dict | None = None,
        score: int = 0,
    ) -> None:
        payload = json.dumps(details or {}, ensure_ascii=False)[:3000]
        created_at = int(time.time())
        try:
            await self.bot.db.execute(
                "INSERT INTO v12_runtime_events "
                "(guild_id,event_type,severity,actor_id,target_id,details_json,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (guild_id, event_type, severity, actor_id, target_id, payload, created_at),
            )
        except Exception:
            logger.debug("V12 runtime event non persisté.", exc_info=True)

        # Reuse the V10 operational center when available, but never make it mandatory.
        if guild_id:
            try:
                await self.bot.db.execute(
                    "INSERT INTO v10_operational_signals "
                    "(guild_id,signal_type,severity,actor_id,target_id,score,details_json,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (guild_id, event_type, severity, actor_id, target_id, score, payload, created_at),
                )
            except Exception:
                pass

    def _alert_allowed(self, guild_id: int, kind: str, cooldown: float = SECURITY_ALERT_COOLDOWN) -> bool:
        key = (guild_id, kind)
        now_m = time.monotonic()
        previous = self._security_alert_at.get(key, 0.0)
        if now_m - previous < cooldown:
            return False
        self._security_alert_at[key] = now_m
        return True

    async def _send_security_notice(self, guild: discord.Guild, title: str, description: str) -> None:
        try:
            conf = await self.bot.db.get_guild_config(guild.id)
        except Exception:
            conf = None

        candidate_ids = []
        if conf:
            for field in ("mod_log_channel", "log_channel", "ticket_log_channel"):
                try:
                    value = conf[field]
                except Exception:
                    value = None
                if value:
                    candidate_ids.append(int(value))

        channel = None
        for channel_id in candidate_ids:
            channel = guild.get_channel(channel_id)
            if channel is not None:
                break
        if channel is None:
            return
        try:
            await channel.send(
                embed=discord.Embed(
                    title=title[:256],
                    description=description[:1800],
                    color=discord.Color.orange(),
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            logger.debug("V12 notice sécurité non envoyée.", exc_info=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        guild_id = member.guild.id
        now_m = time.monotonic()
        joins = self._join_times[guild_id]
        joins.append(now_m)
        while joins and now_m - joins[0] > JOIN_WINDOW_SECONDS:
            joins.popleft()

        try:
            age_seconds = max(0.0, (discord.utils.utcnow() - member.created_at).total_seconds())
        except Exception:
            age_seconds = SUSPICIOUS_ACCOUNT_AGE_SECONDS + 1

        suspicious = age_seconds < SUSPICIOUS_ACCOUNT_AGE_SECONDS
        suspicious_joins = self._suspicious_join_times[guild_id]
        if suspicious:
            suspicious_joins.append(now_m)
        while suspicious_joins and now_m - suspicious_joins[0] > JOIN_WINDOW_SECONDS:
            suspicious_joins.popleft()

        member_scaled_threshold = max(
            JOIN_ALERT_THRESHOLD,
            min(20, max(1, (member.guild.member_count or 0) // 100)),
        )
        raid_like = len(joins) >= member_scaled_threshold
        suspicious_wave = len(suspicious_joins) >= SUSPICIOUS_JOIN_THRESHOLD
        if not (raid_like or suspicious_wave):
            return

        kind = "raid_join_burst" if raid_like else "suspicious_new_accounts"
        if not self._alert_allowed(guild_id, kind):
            return
        severity = "critical" if raid_like and suspicious_wave else "high"
        score = min(100, 55 + len(joins) * 4 + len(suspicious_joins) * 5)
        await self._record_event(
            guild_id,
            kind,
            severity,
            actor_id=member.id,
            details={
                "joins_20s": len(joins),
                "new_accounts_20s": len(suspicious_joins),
                "threshold": member_scaled_threshold,
            },
            score=score,
        )
        await self._send_security_notice(
            member.guild,
            "SentriX V12 — activité d'arrivée inhabituelle",
            (
                f"**{len(joins)}** arrivées détectées sur ~{int(JOIN_WINDOW_SECONDS)} s, "
                f"dont **{len(suspicious_joins)}** compte(s) très récent(s).\n"
                "L'AutoMod existant reste responsable des sanctions ; V12 ajoute ici une détection et une alerte indépendantes."
            ),
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        member = message.author
        if isinstance(member, discord.Member):
            perms = member.guild_permissions
            if perms.administrator or perms.manage_messages:
                return

        key = (message.guild.id, message.author.id)
        now_m = time.monotonic()
        times = self._message_times[key]
        times.append(now_m)
        while times and now_m - times[0] > MESSAGE_WINDOW_SECONDS:
            times.popleft()
        if len(times) < MESSAGE_BURST_THRESHOLD:
            return

        alert_kind = f"message_burst:{message.author.id}"
        if not self._alert_allowed(message.guild.id, alert_kind, MESSAGE_ALERT_COOLDOWN):
            return
        await self._record_event(
            message.guild.id,
            "message_velocity_spike",
            "medium",
            actor_id=message.author.id,
            details={"messages": len(times), "window_seconds": MESSAGE_WINDOW_SECONDS, "channel_id": message.channel.id},
            score=min(90, 35 + len(times) * 4),
        )

    # ----------------------------------------------------------- Ticket SLA

    @tasks.loop(seconds=TICKET_CHECK_SECONDS)
    async def ticket_watch_loop(self) -> None:
        try:
            rows = await self.bot.db.fetchall(
                "SELECT id,guild_id,channel_id,claimed_by,status,created_at "
                "FROM tickets WHERE status='open' ORDER BY created_at ASC LIMIT 500"
            )
        except Exception:
            # Different/legacy ticket schema: the core ticket system keeps running normally.
            return

        now_ts = int(time.time())
        for row in rows:
            ticket_id = int(_row_value(row, "id", 0) or 0)
            guild_id = int(_row_value(row, "guild_id", 0) or 0)
            channel_id = int(_row_value(row, "channel_id", 0) or 0)
            claimed_by = _row_value(row, "claimed_by")
            created_at = int(_row_value(row, "created_at", now_ts) or now_ts)
            if not ticket_id or not guild_id or not channel_id:
                continue

            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            channel = guild.get_channel(channel_id)
            if channel is None:
                await self._record_event(
                    guild_id,
                    "ticket_channel_missing",
                    "medium",
                    target_id=ticket_id,
                    details={"channel_id": channel_id},
                    score=45,
                )
                continue

            try:
                await self.bot.db.execute(
                    "INSERT INTO v12_ticket_watch (ticket_id,guild_id,channel_id,last_reminder_at,last_seen_at) "
                    "VALUES (?,?,?,?,?) ON CONFLICT(ticket_id) DO UPDATE SET "
                    "guild_id=excluded.guild_id,channel_id=excluded.channel_id,last_seen_at=excluded.last_seen_at",
                    (ticket_id, guild_id, channel_id, 0, now_ts),
                )
            except Exception:
                logger.debug("V12: état ticket non persisté ticket=%s", ticket_id, exc_info=True)
                continue

            if claimed_by or now_ts - created_at < TICKET_UNCLAIMED_SECONDS:
                continue
            try:
                watch = await self.bot.db.fetchone(
                    "SELECT last_reminder_at FROM v12_ticket_watch WHERE ticket_id=?",
                    (ticket_id,),
                )
            except Exception:
                continue
            last_reminder = int(_row_value(watch, "last_reminder_at", 0) or 0)
            if now_ts - last_reminder < TICKET_REMINDER_COOLDOWN:
                continue

            try:
                await channel.send(
                    embed=discord.Embed(
                        title="Ticket en attente",
                        description=(
                            "Ce ticket est toujours **non pris en charge**. "
                            "Un membre du staff peut le claim dès qu'il est disponible."
                        ),
                        color=discord.Color.orange(),
                    ),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                await self.bot.db.execute(
                    "UPDATE v12_ticket_watch SET last_reminder_at=? WHERE ticket_id=?",
                    (now_ts, ticket_id),
                )
                await self._record_event(
                    guild_id,
                    "ticket_unclaimed_sla",
                    "medium",
                    target_id=ticket_id,
                    details={"channel_id": channel_id, "age_seconds": now_ts - created_at},
                    score=40,
                )
            except discord.HTTPException:
                logger.debug("V12: rappel ticket non envoyé ticket=%s", ticket_id, exc_info=True)
            except Exception:
                logger.debug("V12: traitement ticket incomplet ticket=%s", ticket_id, exc_info=True)

    @ticket_watch_loop.before_loop
    async def before_ticket_watch_loop(self) -> None:
        await self.bot.wait_until_ready()

    @ticket_watch_loop.error
    async def ticket_watch_error(self, error: Exception) -> None:
        logger.warning(
            "V12: boucle tickets interrompue; maintenance la relancera.",
            exc_info=(type(error), error, error.__traceback__),
        )

    # ----------------------------------------------------------- Maintenance

    @tasks.loop(minutes=5)
    async def maintenance_loop(self) -> None:
        await self.ensure_integrations()
        now_m = time.monotonic()

        for key, (created, task) in list(self._ai_inflight.items()):
            if task.done() or now_m - created > 90:
                self._ai_inflight.pop(key, None)
        if len(self._ai_inflight) > AI_INFLIGHT_MAX:
            excess = len(self._ai_inflight) - AI_INFLIGHT_MAX
            oldest = sorted(self._ai_inflight.items(), key=lambda item: item[1][0])[:excess]
            for key, _ in oldest:
                self._ai_inflight.pop(key, None)

        for key, (created, _) in list(self._ai_context_cache.items()):
            if now_m - created > AI_CONTEXT_TTL * 4:
                self._ai_context_cache.pop(key, None)

        for registry in (self._join_times, self._suspicious_join_times):
            for key, values in list(registry.items()):
                while values and now_m - values[0] > JOIN_WINDOW_SECONDS:
                    values.popleft()
                if not values:
                    registry.pop(key, None)

        for key, values in list(self._message_times.items()):
            while values and now_m - values[0] > MESSAGE_WINDOW_SECONDS:
                values.popleft()
            if not values:
                self._message_times.pop(key, None)

        for key, when in list(self._security_alert_at.items()):
            if now_m - when > max(SECURITY_ALERT_COOLDOWN, MESSAGE_ALERT_COOLDOWN) * 4:
                self._security_alert_at.pop(key, None)

        # Repair a task that died because of an unexpected exception.
        if not self.ticket_watch_loop.is_running():
            try:
                self.ticket_watch_loop.restart()
            except Exception:
                logger.warning("V12: redémarrage ticket_watch_loop impossible.", exc_info=True)

    @maintenance_loop.before_loop
    async def before_maintenance_loop(self) -> None:
        await self.bot.wait_until_ready()

    @maintenance_loop.error
    async def maintenance_error(self, error: Exception) -> None:
        logger.error(
            "V12: maintenance runtime en erreur.",
            exc_info=(type(error), error, error.__traceback__),
        )


async def setup(bot: commands.Bot) -> None:
    if bot.get_cog("BotV12Machine") is None:
        await bot.add_cog(BotV12Machine(bot))
