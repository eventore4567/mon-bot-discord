"""SentriX V17 — IA, économie, progression et jeux."""
from __future__ import annotations

import asyncio
import heapq
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from itertools import count
from types import MethodType

import discord
from discord import app_commands
from discord.ext import commands

from database.db import now
from utils import ai_service, checks, embeds, helpers, stats_service
from .v17_shared import award_credits, ensure_schema, register_command_policy, state

logger = logging.getLogger("bot.v17-ai-economy-games")
AI_ROLE_QUOTA_ERROR = "__V17_ROLE_QUOTA__"
AI_ROLE_QUOTA_MESSAGE = "Votre quota IA quotidien pour votre rôle est atteint. Réessayez demain ou utilisez un rôle avec une limite supérieure."
AI_PRIORITY_CONCURRENCY = 6

GAME_COMMANDS = {
    "rps", "guess-number", "trivia", "tictactoe", "hangman", "math-quiz", "blackjack", "slots",
    "coinflip", "dice", "luckyroll", "highlow", "memory", "reaction", "scramble", "wordgame",
    "emojiquiz", "colorquiz", "fasttype", "duel", "connect4", "numberduel", "reactionduel",
    "quizduel", "triviastart", "wordrace", "reactionevent", "guessrace", "mathrace", "lastmessage",
    "emoji-race", "adventure", "dungeon", "mining", "fishing", "treasure", "hunt", "explore",
}
ECONOMY_COMMANDS = {
    "daily", "weekly", "work", "rob", "pay", "shop", "buy", "inventory", "sell", "gamble",
    "deposit", "withdraw", "banque", "balance", "economy",
}
FARM_LIMITS = {
    "pay": (8, 600),
    "gamble": (20, 300),
    "buy": (12, 300),
    "rob": (6, 600),
}
MISSION_DEFINITIONS = {
    "daily": {
        "commands": ("Utiliser 5 commandes", "commands_count", 5, 100),
        "games": ("Jouer à 2 mini-jeux", "games_count", 2, 125),
        "economy": ("Faire 2 actions économie", "economy_count", 2, 100),
    },
    "weekly": {
        "commands": ("Utiliser 30 commandes", "commands_count", 30, 450),
        "games": ("Jouer à 10 mini-jeux", "games_count", 10, 600),
        "economy": ("Faire 10 actions économie", "economy_count", 10, 500),
    },
}


class PriorityGate:
    def __init__(self, limit: int):
        self.limit = max(1, int(limit))
        self.active = 0
        self.waiters: list[tuple[int, int, asyncio.Future]] = []
        self.sequence = count()
        self.lock = asyncio.Lock()

    async def acquire(self, priority: int) -> None:
        async with self.lock:
            if self.active < self.limit and not self.waiters:
                self.active += 1
                return
            future = asyncio.get_running_loop().create_future()
            heapq.heappush(self.waiters, (-int(priority), next(self.sequence), future))
        try:
            await future
        except BaseException:
            async with self.lock:
                self.waiters = [item for item in self.waiters if item[2] is not future]
                heapq.heapify(self.waiters)
            raise

    async def release(self) -> None:
        async with self.lock:
            while self.waiters:
                _priority, _seq, future = heapq.heappop(self.waiters)
                if future.cancelled() or future.done():
                    continue
                future.set_result(True)
                return
            self.active = max(0, self.active - 1)

    @asynccontextmanager
    async def slot(self, priority: int):
        await self.acquire(priority)
        try:
            yield
        finally:
            await self.release()


def _ai_gate(bot: commands.Bot) -> PriorityGate:
    runtime = state(bot)
    gate = runtime.get("v17_ai_priority_gate")
    if not isinstance(gate, PriorityGate):
        gate = PriorityGate(AI_PRIORITY_CONCURRENCY)
        runtime["v17_ai_priority_gate"] = gate
    return gate


async def _role_ai_policy(bot: commands.Bot, guild_id: int | None, user_id: int | None):
    if not guild_id or not user_id:
        return None
    guild = bot.get_guild(int(guild_id))
    member = guild.get_member(int(user_id)) if guild else None
    if member is None:
        return None
    role_ids = [role.id for role in member.roles]
    if not role_ids:
        return None
    placeholders = ",".join("?" for _ in role_ids)
    rows = await bot.db.fetchall(
        f"SELECT role_id,daily_limit,priority FROM v17_ai_role_quotas WHERE guild_id=? AND role_id IN ({placeholders})",
        (int(guild_id), *role_ids),
    )
    if not rows:
        return None
    return max(rows, key=lambda row: (int(row["priority"]), int(row["daily_limit"])))


async def _channel_memory_policy(bot: commands.Bot, guild_id: int, channel_id: int, settings: dict) -> tuple[bool, int]:
    row = await bot.db.fetchone(
        "SELECT enabled,memory_minutes FROM v17_ai_channel_memory WHERE guild_id=? AND channel_id=?",
        (guild_id, channel_id),
    )
    if row is None:
        return bool(settings.get("memory_enabled", True)), int(settings.get("memory_minutes", 30) or 30)
    return bool(row["enabled"]), max(1, int(row["memory_minutes"] or 30))


async def _server_ai_context(bot: commands.Bot, guild_id: int | None) -> str:
    if not guild_id:
        return ""
    row = await bot.db.fetchone("SELECT context_text FROM v17_ai_context WHERE guild_id=?", (int(guild_id),))
    return str(row["context_text"] or "")[:8000] if row else ""


def _detect_language(text: str) -> str | None:
    value = str(text or "")
    if any("\u0600" <= ch <= "\u06ff" for ch in value):
        return "arabe"
    if any("\u4e00" <= ch <= "\u9fff" for ch in value):
        return "chinois"
    if any("\u0400" <= ch <= "\u04ff" for ch in value):
        return "russe"
    words = {word.strip(".,!?;:'\"()[]").casefold() for word in value.split()}
    fr = len(words & {"je", "tu", "vous", "le", "la", "les", "un", "une", "avec", "pour", "est", "fait", "fais", "comment"})
    en = len(words & {"i", "you", "the", "a", "an", "with", "for", "is", "how", "please", "can", "make"})
    if fr > en and fr >= 2:
        return "français"
    if en > fr and en >= 2:
        return "anglais"
    return None


def _install_ai_error_code() -> None:
    if getattr(ai_service, "_sentrix_v17_role_quota_code", False):
        return
    current_is_error = ai_service.is_error_code
    current_title = ai_service.error_title
    current_message = ai_service.error_message

    def is_error(value):
        return value == AI_ROLE_QUOTA_ERROR or current_is_error(value)

    def title(value):
        return "Quota IA atteint" if value == AI_ROLE_QUOTA_ERROR else current_title(value)

    def message(value):
        return AI_ROLE_QUOTA_MESSAGE if value == AI_ROLE_QUOTA_ERROR else current_message(value)

    ai_service.is_error_code = is_error
    ai_service.error_title = title
    ai_service.error_message = message
    ai_service._sentrix_v17_role_quota_code = True


def install_ai_pipeline(bot: commands.Bot) -> None:
    cog = bot.get_cog("Ai")
    if cog is None:
        return
    _install_ai_error_code()
    cls = type(cog)

    current_prepare = cls._prepare_and_generate
    if not getattr(current_prepare, "_sentrix_v17_ai_pipeline", False):
        async def prepare_v17(self, *, guild_id, channel_id, user_id, author_name,
                              question, forced_advanced: bool = False, suffix: str = "",
                              command: str = "ai") -> dict:
            settings = await ai_service.get_settings(self.bot, guild_id) if guild_id else dict(ai_service.DEFAULT_AI_SETTINGS)
            if guild_id and not settings["enabled"]:
                return {"ok": False, "error": "L'IA est désactivée sur ce serveur (voir `+aisetup`)."}
            problem = ai_service.moderate_input(question, max_length=settings["max_question_length"])
            if problem:
                return {"ok": False, "error": problem}

            role_policy = await _role_ai_policy(self.bot, guild_id, user_id)
            priority = int(role_policy["priority"] if role_policy else 0)
            effective_daily = int(role_policy["daily_limit"] if role_policy else settings["daily_limit"])

            wait = self._check_cooldown(guild_id or 0, user_id, settings["cooldown_seconds"])
            if wait:
                return {"ok": False, "error": f"Attends encore {wait:.0f}s avant une nouvelle demande."}
            if self._check_minute_limit(guild_id or 0, user_id, settings["per_minute_limit"]):
                return {"ok": False, "error": "Trop de demandes en une minute — patiente un peu."}
            if guild_id:
                used_today = await ai_service.get_daily_usage(self.bot, guild_id, user_id)
                if used_today >= effective_daily:
                    label = "pour ton rôle" if role_policy else "sur ce serveur"
                    return {"ok": False, "error": f"Limite quotidienne atteinte ({effective_daily} demandes/jour {label})."}

            model_key = ai_service.pick_model(question, forced_advanced=forced_advanced)
            if settings["default_model"] == ai_service.MODEL_LUNA and not forced_advanced:
                model_key = ai_service.MODEL_LUNA
            elif settings["default_model"] == ai_service.MODEL_SOL:
                model_key = ai_service.MODEL_SOL
            reasoning_effort = ai_service.pick_reasoning_effort(model_key, settings["reasoning_effort"])

            memory_enabled = False
            memory_minutes = int(settings.get("memory_minutes", 30) or 30)
            previous_response_id = None
            if guild_id:
                memory_enabled, memory_minutes = await _channel_memory_policy(self.bot, guild_id, channel_id, settings)
                if memory_enabled:
                    _, previous_response_id = await ai_service.get_conversation_history(
                        self.bot, guild_id, channel_id, user_id, memory_minutes,
                    )

            instructions = await self._build_system_instructions(user_id, author_name)
            server_context = await _server_ai_context(self.bot, guild_id)
            if server_context:
                instructions += (
                    "\n\nContexte officiel configuré par les administrateurs de ce serveur Discord. "
                    "Utilise-le pour répondre aux questions sur ce serveur, sans inventer ce qui n'y figure pas :\n"
                    + server_context
                )
            detected = _detect_language(question)
            if detected:
                instructions += f"\n\nLa langue détectée pour la demande actuelle est le {detected}. Réponds dans cette langue sauf demande contraire."

            prompt = question + suffix
            async with _ai_gate(self.bot).slot(priority):
                result = await ai_service.generate(
                    prompt,
                    model_key=model_key,
                    reasoning_effort=reasoning_effort,
                    previous_response_id=previous_response_id,
                    instructions=instructions,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    user_id=user_id,
                    command=command,
                    web_search=ai_service.needs_web_search(question),
                )
            if not result.ok:
                return {"ok": False, "error": ai_service.error_message(result.error)}
            if guild_id:
                tokens = ai_service.estimate_tokens(prompt) + ai_service.estimate_tokens(result.text)
                await ai_service.record_usage(self.bot, guild_id, user_id, tokens_estimate=tokens)
                if memory_enabled:
                    await ai_service.append_conversation(self.bot, guild_id, channel_id, user_id, "user", question)
                    await ai_service.append_conversation(self.bot, guild_id, channel_id, user_id, "assistant", result.text, response_id=result.response_id)
            return {"ok": True, "text": result.text, "model_key": result.model_key or model_key}

        prepare_v17._sentrix_v17_ai_pipeline = True
        prepare_v17._sentrix_original = current_prepare
        cls._prepare_and_generate = prepare_v17

    current_ask = cls.ask_ai
    if not getattr(current_ask, "_sentrix_v17_legacy_ai", False):
        async def ask_ai_v17(self, prompt, history: list = None, author_name: str = None, *,
                             guild_id: int = None, channel_id: int = None, user_id: int = None,
                             command: str = None) -> str:
            settings = await ai_service.get_settings(self.bot, guild_id) if guild_id else dict(ai_service.DEFAULT_AI_SETTINGS)
            role_policy = await _role_ai_policy(self.bot, guild_id, user_id)
            daily_limit = int(role_policy["daily_limit"] if role_policy else settings["daily_limit"])
            priority = int(role_policy["priority"] if role_policy else 0)
            if guild_id and user_id and await ai_service.get_daily_usage(self.bot, guild_id, user_id) >= daily_limit:
                return AI_ROLE_QUOTA_ERROR
            model_key = ai_service.pick_model(prompt if isinstance(prompt, str) else "")
            effort = ai_service.pick_reasoning_effort(model_key, "medium")
            instructions = await self._build_system_instructions(user_id, author_name)
            server_context = await _server_ai_context(self.bot, guild_id)
            if server_context:
                instructions += "\n\nContexte officiel du serveur :\n" + server_context
            detected = _detect_language(str(prompt))
            if detected:
                instructions += f"\n\nRéponds en {detected} pour cette demande sauf instruction contraire."
            payload = list(history) + [{"role": "user", "content": prompt}] if history else prompt
            async with _ai_gate(self.bot).slot(priority):
                result = await ai_service.generate(
                    payload,
                    model_key=model_key,
                    reasoning_effort=effort,
                    instructions=instructions,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    user_id=user_id,
                    command=command,
                    web_search=ai_service.needs_web_search(prompt),
                )
            if not result.ok:
                return result.error
            if guild_id and user_id:
                await ai_service.record_usage(self.bot, guild_id, user_id, ai_service.estimate_tokens(str(prompt)) + ai_service.estimate_tokens(result.text))
            return result.text

        ask_ai_v17._sentrix_v17_legacy_ai = True
        ask_ai_v17._sentrix_original = current_ask
        cls.ask_ai = ask_ai_v17

    current_confidence = cls.ask_ai_with_confidence
    if not getattr(current_confidence, "_sentrix_v17_legacy_ai", False):
        async def confidence_v17(self, prompt: str, history: list = None, *, guild_id: int = None,
                                 channel_id: int = None, user_id: int = None, command: str = None):
            settings = await ai_service.get_settings(self.bot, guild_id) if guild_id else dict(ai_service.DEFAULT_AI_SETTINGS)
            role_policy = await _role_ai_policy(self.bot, guild_id, user_id)
            limit = int(role_policy["daily_limit"] if role_policy else settings["daily_limit"])
            priority = int(role_policy["priority"] if role_policy else 0)
            if guild_id and user_id and await ai_service.get_daily_usage(self.bot, guild_id, user_id) >= limit:
                return AI_ROLE_QUOTA_ERROR, 0
            model_key = ai_service.pick_model(prompt)
            effort = ai_service.pick_reasoning_effort(model_key, "medium")
            instructions = await self._build_system_instructions(user_id)
            instructions += "\n\nTermine TOUJOURS par : CONFIANCE: X/10"
            context = await _server_ai_context(self.bot, guild_id)
            if context:
                instructions += "\n\nContexte officiel du serveur :\n" + context
            payload = list(history) + [{"role": "user", "content": prompt}] if history else prompt
            async with _ai_gate(self.bot).slot(priority):
                result = await ai_service.generate(
                    payload, model_key=model_key, reasoning_effort=effort, instructions=instructions,
                    guild_id=guild_id, channel_id=channel_id, user_id=user_id, command=command,
                    web_search=ai_service.needs_web_search(prompt) or command == "fact-check",
                )
            if not result.ok:
                return result.error, 0
            content = result.text or ""
            confidence = 8
            import re
            match = re.search(r"CONFIANCE\s*:\s*(\d{1,2})\s*/\s*10", content, re.IGNORECASE)
            if match:
                confidence = max(1, min(10, int(match.group(1))))
                content = content[:match.start()].rstrip(" \n-")
            if guild_id and user_id:
                await ai_service.record_usage(self.bot, guild_id, user_id, ai_service.estimate_tokens(prompt) + ai_service.estimate_tokens(content))
            return content, confidence

        confidence_v17._sentrix_v17_legacy_ai = True
        confidence_v17._sentrix_original = current_confidence
        cls.ask_ai_with_confidence = confidence_v17

    install_ai_buttons(bot)
    state(bot)["v17_ai_pipeline"] = True


def install_ai_buttons(bot: commands.Bot) -> None:
    from . import ai as ai_mod
    view_cls = ai_mod.AiResponseView
    if getattr(view_cls, "_sentrix_v17_buttons", False):
        return

    original_init = view_cls.__init__
    original_check = view_cls.interaction_check

    def init_v17(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._v17_active_task = None

        correct = discord.ui.Button(
            label="Corriger",
            style=discord.ButtonStyle.secondary,
            row=0,
            custom_id="sentrix:v17:ai:correct",
        )
        async def correct_cb(interaction: discord.Interaction):
            await self._regenerate(
                interaction,
                "\n\nCorrige la réponse précédente : orthographe, grammaire, formulation et éventuelles incohérences. Retourne la version corrigée.",
            )
        correct.callback = correct_cb
        self.add_item(correct)

        stop = discord.ui.Button(
            label="Arrêter",
            style=discord.ButtonStyle.danger,
            row=1,
            custom_id="sentrix:v17:ai:stop",
            disabled=True,
        )
        async def stop_cb(interaction: discord.Interaction):
            task = getattr(self, "_v17_active_task", None)
            if task is not None and not task.done():
                task.cancel()
            self.busy = False
            for child in self.children:
                child.disabled = False
            stop.disabled = True
            try:
                await interaction.response.edit_message(content="Génération arrêtée.", embed=embeds.info("La génération en cours a été interrompue."), view=self)
            except discord.HTTPException:
                if not interaction.response.is_done():
                    await interaction.response.send_message("Génération arrêtée.", ephemeral=True)
        stop.callback = stop_cb
        self.add_item(stop)

    async def check_v17(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=embeds.error("Seul l'auteur de la demande peut utiliser ces boutons."), ephemeral=True)
            return False
        custom_id = str((interaction.data or {}).get("custom_id", "")) if isinstance(interaction.data, dict) else ""
        if custom_id == "sentrix:v17:ai:stop":
            return True
        return await original_check(self, interaction)

    async def regenerate_v17(self, interaction: discord.Interaction, suffix: str):
        self.busy = True
        self._v17_active_task = asyncio.current_task()
        stop_button = None
        for item in self.children:
            if getattr(item, "custom_id", None) == "sentrix:v17:ai:stop":
                stop_button = item
                item.disabled = False
            else:
                item.disabled = True
        try:
            try:
                await interaction.response.edit_message(content="SentriX réfléchit…", embed=None, view=self)
            except discord.HTTPException:
                pass
            result = await self.cog._prepare_and_generate(
                guild_id=self.guild_id,
                channel_id=self.channel_id,
                user_id=self.author_id,
                author_name=str(interaction.user),
                question=self.question,
                suffix=suffix,
                command="ai-regenerate",
            )
            for item in self.children:
                item.disabled = False
            if stop_button is not None:
                stop_button.disabled = True
            if not result["ok"]:
                await interaction.edit_original_response(content=None, embed=embeds.error(result["error"]), view=self)
                return
            self.model_key = result["model_key"]
            answer = result["text"] or "…"
            if ai_service.needs_file_fallback(answer) or len(answer) > 1000:
                await interaction.edit_original_response(content=None, embed=None, view=None)
                fake_ctx = ai_mod._FakeCtxForDelivery(self.cog.bot, interaction, self.channel_id)
                await self.cog._deliver_answer(fake_ctx, self.question, result, thinking_msg=None)
                return
            embed = self.cog._build_ai_embed(self.question, answer, self.model_key, interaction.user)
            await interaction.edit_original_response(content=None, embed=embed, view=self)
        except asyncio.CancelledError:
            return
        finally:
            if getattr(self, "_v17_active_task", None) is asyncio.current_task():
                self._v17_active_task = None
            self.busy = False

    view_cls.__init__ = init_v17
    view_cls.interaction_check = check_v17
    view_cls._regenerate = regenerate_v17
    view_cls._sentrix_v17_buttons = True


def install_shop_atomic_rules(bot: commands.Bot) -> None:
    db = getattr(bot, "db", None)
    if db is None or getattr(db.purchase_shop_item, "_sentrix_v17_shop_rules", False):
        return
    original = db.purchase_shop_item

    async def purchase_v17(_db, guild_id: int, user_id: int, item_id: int):
        conn = _db._conn
        async with _db._economy_lock:
            cur = await conn.execute("SELECT * FROM shop_items WHERE guild_id=? AND id=?", (guild_id, item_id))
            row = await cur.fetchone()
            await cur.close()
            if not row:
                return "not_found", None
            item = dict(row)
            base_price = int(item.get("price") or 0)
            if base_price <= 0:
                return "not_found", None
            rule_cur = await conn.execute("SELECT * FROM v17_shop_rules WHERE guild_id=? AND item_id=?", (guild_id, item_id))
            rule = await rule_cur.fetchone()
            await rule_cur.close()
            stamp = now()
            if rule:
                if rule["available_from"] and stamp < int(rule["available_from"]):
                    return "not_found", item
                if rule["available_until"] and stamp > int(rule["available_until"]):
                    return "not_found", item
                if int(rule["stock"] or 0) == 0:
                    return "not_found", item
                if rule["sale_price"] and int(rule["sale_price"]) > 0 and (not rule["sale_ends_at"] or stamp <= int(rule["sale_ends_at"])):
                    item["price"] = min(base_price, int(rule["sale_price"]))
            price = int(item["price"])
            role_id = item.get("role_id")
            if role_id:
                reservation = await conn.execute(
                    "INSERT OR IGNORE INTO shop_role_purchases (guild_id,user_id,role_id,item_id,price_paid,purchased_at) VALUES (?,?,?,?,?,?)",
                    (guild_id, user_id, role_id, item_id, price, stamp),
                )
                if reservation.rowcount < 1:
                    return "already_owned", item
            await conn.execute("INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)", (guild_id, user_id))
            bal_cur = await conn.execute("SELECT cash FROM economy WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            balance = await bal_cur.fetchone()
            await bal_cur.close()
            if not balance or int(balance["cash"]) < price:
                if role_id:
                    await conn.execute("DELETE FROM shop_role_purchases WHERE guild_id=? AND user_id=? AND role_id=?", (guild_id, user_id, role_id))
                await conn.commit()
                return "insufficient_funds", item
            await conn.execute("UPDATE economy SET cash=cash-? WHERE guild_id=? AND user_id=?", (price, guild_id, user_id))
            await conn.execute(
                "INSERT INTO economy_transactions (guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) VALUES (?,?,NULL,'buy',?,?,?)",
                (guild_id, user_id, price, stamp, f"Achat : {item['name']}"),
            )
            if rule and int(rule["stock"] or -1) > 0:
                await conn.execute("UPDATE v17_shop_rules SET stock=stock-1,updated_at=? WHERE guild_id=? AND item_id=? AND stock>0", (stamp, guild_id, item_id))
            await conn.commit()
            return "ok", item

    purchase_v17._sentrix_v17_shop_rules = True
    purchase_v17._sentrix_original = original
    db.purchase_shop_item = MethodType(purchase_v17, db)


def install_economy_antifarm(bot: commands.Bot) -> None:
    runtime = state(bot)
    if runtime.get("v17_economy_antifarm"):
        return

    async def economy_check(ctx: commands.Context) -> bool:
        if ctx.guild is None or ctx.command is None:
            return True
        root = (ctx.command.root_parent or ctx.command).name.casefold()
        if root not in FARM_LIMITS:
            return True
        limit, window = FARM_LIMITS[root]
        member = ctx.author if isinstance(ctx.author, discord.Member) else None
        if member is not None and (discord.utils.utcnow() - member.created_at).total_seconds() < 7 * 86400:
            limit = max(2, limit // 2)
        key = (ctx.guild.id, ctx.author.id, root)
        buckets = state(bot)["economy_buckets"]
        bucket = buckets.setdefault(key, [])
        mono = time.monotonic()
        bucket[:] = [stamp for stamp in bucket if mono - stamp <= window]
        if len(bucket) >= limit:
            from .bot_excellence_runtime import RuntimeRateLimitError
            retry = max(1, int(window - (mono - bucket[0])))
            raise RuntimeRateLimitError(f"Anti-farm : trop d'utilisations de +{root}. Réessayez dans environ {retry}s.")
        bucket.append(mono)
        return True

    bot.add_check(economy_check)
    runtime["v17_economy_antifarm"] = True


def _period_keys() -> tuple[str, str]:
    current = datetime.now(timezone.utc)
    daily = current.strftime("%Y-%m-%d")
    iso = current.isocalendar()
    weekly = f"{iso.year}-W{iso.week:02d}"
    return daily, weekly


async def _unlock_achievement(bot, guild_id: int, user_id: int, key: str, reward: int) -> bool:
    conn = bot.db._conn
    async with bot.db._economy_lock:
        cur = await conn.execute(
            "INSERT OR IGNORE INTO v17_achievements (guild_id,user_id,achievement_key,reward,unlocked_at) VALUES (?,?,?,?,?)",
            (guild_id, user_id, key, reward, now()),
        )
        if cur.rowcount < 1:
            return False
        await conn.execute("INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)", (guild_id, user_id))
        await conn.execute("UPDATE economy SET cash=cash+? WHERE guild_id=? AND user_id=?", (reward, guild_id, user_id))
        await conn.execute(
            "INSERT INTO economy_transactions (guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) VALUES (?,NULL,?,'achievement',?,?,?)",
            (guild_id, user_id, reward, now(), key),
        )
        await conn.commit()
        return True


class GameLobbyView(discord.ui.View):
    def __init__(self, cog: "V17AIEconomyGames", ctx: commands.Context, game: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.ctx = ctx
        self.game = game.casefold()
        self.players = [ctx.author.id]
        self.spectators: set[int] = set()
        self.message: discord.Message | None = None

    def embed(self) -> discord.Embed:
        players = "\n".join(f"• <@{uid}>" for uid in self.players) or "Aucun"
        spectators = "\n".join(f"• <@{uid}>" for uid in self.spectators) or "Aucun"
        e = embeds.neutral(f"Lobby — {self.game}", "Rejoignez la partie ou observez-la avant le lancement.")
        e.add_field(name=f"Joueurs ({len(self.players)})", value=players, inline=True)
        e.add_field(name=f"Spectateurs ({len(self.spectators)})", value=spectators, inline=True)
        return e

    @discord.ui.button(label="Rejoindre", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if interaction.user.id not in self.players:
            self.players.append(interaction.user.id)
        self.spectators.discard(interaction.user.id)
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Spectateur", style=discord.ButtonStyle.secondary)
    async def spectate(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if interaction.user.id not in self.players:
            self.spectators.add(interaction.user.id)
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Quitter", style=discord.ButtonStyle.secondary)
    async def leave(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if interaction.user.id == self.ctx.author.id:
            return await interaction.response.send_message("Le créateur du lobby doit fermer le lobby au lieu de le quitter.", ephemeral=True)
        if interaction.user.id in self.players:
            self.players.remove(interaction.user.id)
        self.spectators.discard(interaction.user.id)
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Lancer", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Seul le créateur du lobby peut lancer la partie.", ephemeral=True)
        if len(self.players) < 2:
            return await interaction.response.send_message("Il faut au moins deux joueurs.", ephemeral=True)
        opponent = interaction.guild.get_member(self.players[1])
        command = self.cog.bot.get_command(self.game)
        await interaction.response.edit_message(embed=embeds.success("Lobby lancé."), view=None)
        if command is not None and opponent is not None and "adversaire" in command.clean_params:
            try:
                await self.ctx.invoke(command, adversaire=opponent)
                self.stop()
                return
            except Exception:
                logger.debug("Lancement automatique du lobby impossible.", exc_info=True)
        prefix = getattr(self.ctx, "clean_prefix", "+") or "+"
        await interaction.followup.send(f"Joueurs prêts : <@{self.players[0]}> vs <@{self.players[1]}>. Lancez `{prefix}{self.game} @adversaire`.")
        self.stop()


class V17AIEconomyGames(commands.Cog, name="V17AIEconomyGames"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.matchmaking: dict[tuple[int, str], list[tuple[commands.Context, float]]] = {}

    async def cog_load(self):
        await ensure_schema(self.bot)

    @commands.hybrid_command(name="aimemorychannel", description="Configurer la mémoire IA de ce salon.", with_app_command=False)
    @checks.is_owner_or_admin_for("ai")
    async def aimemorychannel(self, ctx: commands.Context, mode: str, minutes: int = 30, salon: discord.TextChannel | None = None):
        channel = salon or ctx.channel
        mode = mode.casefold().strip()
        if mode not in {"on", "off", "activer", "desactiver", "désactiver"}:
            return await ctx.send(embed=embeds.error("Mode valide : `on` ou `off`."))
        enabled = mode in {"on", "activer"}
        minutes = max(1, min(1440, int(minutes)))
        await self.bot.db.execute(
            "INSERT INTO v17_ai_channel_memory (guild_id,channel_id,enabled,memory_minutes) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id,channel_id) DO UPDATE SET enabled=excluded.enabled,memory_minutes=excluded.memory_minutes",
            (ctx.guild.id, channel.id, int(enabled), minutes),
        )
        await ctx.send(embed=embeds.success(f"Mémoire IA {'activée' if enabled else 'désactivée'} dans {channel.mention} ({minutes} min)."))

    @commands.hybrid_group(name="airolequota", description="Quotas et priorité IA par rôle.")
    @checks.is_owner_or_admin_for("ai")
    async def airolequota(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT * FROM v17_ai_role_quotas WHERE guild_id=? ORDER BY priority DESC,daily_limit DESC", (ctx.guild.id,))
        text = "\n".join(f"• <@&{r['role_id']}> — **{r['daily_limit']}/jour** — priorité **{r['priority']}**" for r in rows) or "Aucun quota par rôle."
        await ctx.send(embed=embeds.info(text, title="Quotas IA par rôle"))

    @airolequota.command(name="set")
    async def airolequota_set(self, ctx: commands.Context, role: discord.Role, daily_limit: app_commands.Range[int, 1, 10000], priority: app_commands.Range[int, 0, 100] = 0):
        await self.bot.db.execute(
            "INSERT INTO v17_ai_role_quotas (guild_id,role_id,daily_limit,priority) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id,role_id) DO UPDATE SET daily_limit=excluded.daily_limit,priority=excluded.priority",
            (ctx.guild.id, role.id, daily_limit, priority),
        )
        await ctx.send(embed=embeds.success(f"{role.mention} : **{daily_limit} demandes/jour**, priorité **{priority}**."))

    @airolequota.command(name="remove")
    async def airolequota_remove(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.execute("DELETE FROM v17_ai_role_quotas WHERE guild_id=? AND role_id=?", (ctx.guild.id, role.id))
        await ctx.send(embed=embeds.success(f"Quota spécial retiré pour {role.mention}."))

    @commands.hybrid_group(name="aicontext", description="Règlement/FAQ/contexte officiel fourni à SentriX AI.")
    @checks.is_owner_or_admin_for("ai")
    async def aicontext(self, ctx: commands.Context):
        text = await self.bot.db.fetchone("SELECT context_text FROM v17_ai_context WHERE guild_id=?", (ctx.guild.id,))
        await ctx.send(embed=embeds.info((text["context_text"] if text else "Aucun contexte configuré.")[:4000], title="Contexte IA du serveur"))

    @aicontext.command(name="set")
    async def aicontext_set(self, ctx: commands.Context, *, texte: str):
        if len(texte) > 8000:
            return await ctx.send(embed=embeds.error("Le contexte est limité à 8000 caractères."))
        await self.bot.db.execute(
            "INSERT INTO v17_ai_context (guild_id,context_text,updated_by,updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET context_text=excluded.context_text,updated_by=excluded.updated_by,updated_at=excluded.updated_at",
            (ctx.guild.id, texte, ctx.author.id, now()),
        )
        await ctx.send(embed=embeds.success("Contexte IA du serveur mis à jour."))

    @aicontext.command(name="clear")
    async def aicontext_clear(self, ctx: commands.Context):
        await self.bot.db.execute("DELETE FROM v17_ai_context WHERE guild_id=?", (ctx.guild.id,))
        await ctx.send(embed=embeds.success("Contexte IA supprimé."))

    @commands.hybrid_command(name="transactions", description="Afficher l'historique des transactions économiques.", with_app_command=False)
    async def transactions(self, ctx: commands.Context, membre: discord.Member | None = None):
        target = membre or ctx.author
        if target.id != ctx.author.id and not ctx.author.guild_permissions.manage_guild:
            return await ctx.send(embed=embeds.error("Il faut la permission Gérer le serveur pour voir les transactions d'un autre membre."))
        rows = await self.bot.db.get_transactions(ctx.guild.id, target.id, limit=15)
        if not rows:
            return await ctx.send(embed=embeds.info("Aucune transaction enregistrée."))
        lines = []
        for row in rows:
            direction = "+" if row["receiver_id"] == target.id else "-"
            lines.append(f"{direction} **{stats_service.format_number(row['amount'])}** — `{row['transaction_type']}` — <t:{row['created_at']}:R> — {row['reason'] or '—'}")
        await ctx.send(embed=embeds.info("\n".join(lines)[:4000], title=f"Transactions — {target.display_name}"))

    @commands.hybrid_command(name="shopstock", description="Configurer le stock d'un article de boutique.", with_app_command=False)
    @checks.is_owner_or_admin_for("economie")
    async def shopstock(self, ctx: commands.Context, item_id: int, stock: int):
        if stock < -1:
            return await ctx.send(embed=embeds.error("Utilisez `-1` pour un stock illimité, ou 0+ pour un stock précis."))
        item = await self.bot.db.fetchone("SELECT name FROM shop_items WHERE guild_id=? AND id=?", (ctx.guild.id, item_id))
        if not item:
            return await ctx.send(embed=embeds.error("Article introuvable."))
        await self.bot.db.execute(
            "INSERT INTO v17_shop_rules (guild_id,item_id,stock,updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id,item_id) DO UPDATE SET stock=excluded.stock,updated_at=excluded.updated_at",
            (ctx.guild.id, item_id, stock, now()),
        )
        await ctx.send(embed=embeds.success(f"Stock de **{item['name']}** : **{'illimité' if stock == -1 else stock}**."))

    @commands.hybrid_command(name="shoppromo", description="Créer une promotion temporaire sur un article.", with_app_command=False)
    @checks.is_owner_or_admin_for("economie")
    async def shoppromo(self, ctx: commands.Context, item_id: int, prix: int, duree: str = "24h"):
        item = await self.bot.db.fetchone("SELECT name,price FROM shop_items WHERE guild_id=? AND id=?", (ctx.guild.id, item_id))
        if not item:
            return await ctx.send(embed=embeds.error("Article introuvable."))
        seconds = helpers.parse_duration(duree)
        if seconds is None or seconds <= 0 or prix <= 0 or prix >= int(item["price"]):
            return await ctx.send(embed=embeds.error("Prix promo invalide ou durée invalide. Le prix doit être inférieur au prix normal."))
        await self.bot.db.execute(
            "INSERT INTO v17_shop_rules (guild_id,item_id,stock,sale_price,sale_ends_at,updated_at) VALUES (?,?,-1,?,?,?) "
            "ON CONFLICT(guild_id,item_id) DO UPDATE SET sale_price=excluded.sale_price,sale_ends_at=excluded.sale_ends_at,updated_at=excluded.updated_at",
            (ctx.guild.id, item_id, prix, now() + seconds, now()),
        )
        await ctx.send(embed=embeds.success(f"Promotion sur **{item['name']}** : **{prix}** jusqu'à <t:{now()+seconds}:R>."))

    @commands.hybrid_command(name="achievements", description="Afficher les succès débloqués.", with_app_command=False)
    async def achievements(self, ctx: commands.Context, membre: discord.Member | None = None):
        target = membre or ctx.author
        rows = await self.bot.db.fetchall(
            "SELECT * FROM v17_achievements WHERE guild_id=? AND user_id=? ORDER BY unlocked_at DESC",
            (ctx.guild.id, target.id),
        )
        labels = {
            "first_command": "Première commande",
            "commander_100": "100 commandes",
            "gamer_10": "10 actions de mini-jeu",
            "wealth_1000": "1000 pièces de patrimoine",
        }
        text = "\n".join(f"• **{labels.get(r['achievement_key'], r['achievement_key'])}** — +{r['reward']} 🪙 — <t:{r['unlocked_at']}:R>" for r in rows) or "Aucun succès débloqué."
        await ctx.send(embed=embeds.info(text, title=f"Succès — {target.display_name}"))

    @commands.hybrid_command(name="missions", description="Voir et réclamer automatiquement les missions quotidiennes/hebdomadaires.")
    async def missions(self, ctx: commands.Context):
        daily_key, weekly_key = _period_keys()
        lines = []
        total_reward = 0
        for kind, period_key in (("daily", daily_key), ("weekly", weekly_key)):
            row = await self.bot.db.fetchone(
                "SELECT * FROM v17_activity_counters WHERE guild_id=? AND user_id=? AND period_kind=? AND period_key=?",
                (ctx.guild.id, ctx.author.id, kind, period_key),
            )
            values = dict(row) if row else {"commands_count": 0, "games_count": 0, "economy_count": 0}
            lines.append(f"**{'Aujourd’hui' if kind == 'daily' else 'Cette semaine'}**")
            for mission_key, (label, field, target, reward) in MISSION_DEFINITIONS[kind].items():
                current = int(values.get(field, 0) or 0)
                claimed = await self.bot.db.fetchone(
                    "SELECT 1 FROM v17_mission_claims WHERE guild_id=? AND user_id=? AND period_kind=? AND period_key=? AND mission_key=?",
                    (ctx.guild.id, ctx.author.id, kind, period_key, mission_key),
                )
                if current >= target and not claimed:
                    cur = await self.bot.db.execute(
                        "INSERT OR IGNORE INTO v17_mission_claims (guild_id,user_id,period_kind,period_key,mission_key,reward,claimed_at) VALUES (?,?,?,?,?,?,?)",
                        (ctx.guild.id, ctx.author.id, kind, period_key, mission_key, reward, now()),
                    )
                    if cur.rowcount > 0:
                        await award_credits(self.bot, ctx.guild.id, ctx.author.id, reward, "mission", f"Mission {kind}:{mission_key}")
                        total_reward += reward
                        claimed = True
                marker = "✓" if claimed else ("●" if current >= target else "○")
                lines.append(f"{marker} {label} — **{min(current, target)}/{target}** — {reward} 🪙")
        if total_reward:
            lines.append(f"\n**Récompenses réclamées maintenant : +{total_reward} 🪙**")
        await ctx.send(embed=embeds.info("\n".join(lines), title="Missions SentriX"))

    @commands.hybrid_group(name="season", description="Saisons temporaires sans réinitialiser l'économie ou les niveaux.")
    async def season(self, ctx: commands.Context):
        season = await self.bot.db.fetchone("SELECT * FROM v17_seasons WHERE guild_id=? AND active=1 AND ends_at>? ORDER BY id DESC LIMIT 1", (ctx.guild.id, now()))
        if not season:
            return await ctx.send(embed=embeds.info("Aucune saison active."))
        points = await self.bot.db.fetchone("SELECT points FROM v17_season_points WHERE season_id=? AND user_id=?", (season["id"], ctx.author.id))
        await ctx.send(embed=embeds.info(
            f"**{season['name']}**\nFin : <t:{season['ends_at']}:R>\nVos points : **{int(points['points'] if points else 0)}**",
            title="Saison active",
        ))

    @season.command(name="start")
    @checks.is_owner_or_admin_for("economie")
    async def season_start(self, ctx: commands.Context, duree: str, *, nom: str = "Saison SentriX"):
        seconds = helpers.parse_duration(duree)
        if seconds is None or seconds < 3600:
            return await ctx.send(embed=embeds.error("Durée minimale : 1 heure. Exemples : `7j`, `30j`."))
        await self.bot.db.execute("UPDATE v17_seasons SET active=0 WHERE guild_id=? AND active=1", (ctx.guild.id,))
        await self.bot.db.execute(
            "INSERT INTO v17_seasons (guild_id,name,starts_at,ends_at,active,created_by,created_at) VALUES (?,?,?,?,1,?,?)",
            (ctx.guild.id, nom[:100], now(), now() + seconds, ctx.author.id, now()),
        )
        await ctx.send(embed=embeds.success(f"Saison **{nom}** lancée jusqu'à <t:{now()+seconds}:F>. Les données permanentes ne sont pas réinitialisées."))

    @season.command(name="top")
    async def season_top(self, ctx: commands.Context):
        season = await self.bot.db.fetchone("SELECT * FROM v17_seasons WHERE guild_id=? ORDER BY active DESC,id DESC LIMIT 1", (ctx.guild.id,))
        if not season:
            return await ctx.send(embed=embeds.info("Aucune saison."))
        rows = await self.bot.db.fetchall("SELECT user_id,points FROM v17_season_points WHERE season_id=? ORDER BY points DESC LIMIT 10", (season["id"],))
        text = "\n".join(f"**{i}.** <@{r['user_id']}> — {r['points']} pts" for i, r in enumerate(rows, 1)) or "Aucun point."
        await ctx.send(embed=embeds.info(text, title=f"Classement — {season['name']}"))

    @season.command(name="end")
    @checks.is_owner_or_admin_for("economie")
    async def season_end(self, ctx: commands.Context):
        await self.bot.db.execute("UPDATE v17_seasons SET active=0,ends_at=? WHERE guild_id=? AND active=1", (now(), ctx.guild.id))
        await ctx.send(embed=embeds.success("Saison terminée. Le classement reste archivé."))

    @commands.hybrid_command(name="gamelobby", description="Créer un lobby multijoueur avec joueurs et spectateurs.", with_app_command=False)
    async def gamelobby(self, ctx: commands.Context, jeu: str):
        game = jeu.casefold().strip()
        command = self.bot.get_command(game)
        if command is None or game not in GAME_COMMANDS:
            return await ctx.send(embed=embeds.error("Mini-jeu inconnu ou non compatible avec les lobbies V17."))
        view = GameLobbyView(self, ctx, game)
        message = await ctx.send(embed=view.embed(), view=view)
        view.message = message

    @commands.hybrid_command(name="matchmake", description="Chercher automatiquement un adversaire pour un duel/mini-jeu.", with_app_command=False)
    async def matchmake(self, ctx: commands.Context, jeu: str = "tictactoe"):
        game = jeu.casefold().strip()
        command = self.bot.get_command(game)
        if command is None or game not in GAME_COMMANDS:
            return await ctx.send(embed=embeds.error("Jeu introuvable."))
        key = (ctx.guild.id, game)
        queue = self.matchmaking.setdefault(key, [])
        mono = time.monotonic()
        queue[:] = [(queued_ctx, stamp) for queued_ctx, stamp in queue if mono - stamp < 180 and queued_ctx.author.id != ctx.author.id]
        if queue:
            first_ctx, _stamp = queue.pop(0)
            first_member = ctx.guild.get_member(first_ctx.author.id)
            if first_member is None:
                return await ctx.send(embed=embeds.warning("L'adversaire précédent n'est plus disponible. Relancez la recherche."))
            await ctx.send(embed=embeds.success(f"Match trouvé : {first_member.mention} vs {ctx.author.mention}."))
            try:
                if "adversaire" in command.clean_params:
                    await first_ctx.invoke(command, adversaire=ctx.author)
                    return
            except Exception:
                logger.debug("Démarrage matchmaking automatique impossible.", exc_info=True)
            prefix = getattr(ctx, "clean_prefix", "+") or "+"
            return await ctx.send(f"Lancez `{prefix}{game} {ctx.author.mention}` pour démarrer.")
        queue.append((ctx, mono))
        await ctx.send(embed=embeds.info(f"Recherche d'un adversaire pour **{game}**… La file expire dans 3 minutes."))

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context):
        if ctx.guild is None or ctx.command is None or ctx.author.bot:
            return
        asyncio.create_task(self._record_activity(ctx), name=f"sentrix-v17-activity-{ctx.guild.id}-{ctx.author.id}")

    async def _record_activity(self, ctx: commands.Context):
        try:
            root = (ctx.command.root_parent or ctx.command).name.casefold()
            daily_key, weekly_key = _period_keys()
            game_inc = 1 if root in GAME_COMMANDS else 0
            economy_inc = 1 if root in ECONOMY_COMMANDS else 0
            conn = self.bot.db._conn
            for kind, period_key in (("daily", daily_key), ("weekly", weekly_key)):
                await conn.execute(
                    "INSERT INTO v17_activity_counters (guild_id,user_id,period_kind,period_key,commands_count,games_count,economy_count,updated_at) "
                    "VALUES (?,?,?,?,1,?,?,?) ON CONFLICT(guild_id,user_id,period_kind,period_key) DO UPDATE SET "
                    "commands_count=commands_count+1,games_count=games_count+excluded.games_count,economy_count=economy_count+excluded.economy_count,updated_at=excluded.updated_at",
                    (ctx.guild.id, ctx.author.id, kind, period_key, game_inc, economy_inc, now()),
                )
            season = await self.bot.db.fetchone("SELECT id FROM v17_seasons WHERE guild_id=? AND active=1 AND ends_at>? ORDER BY id DESC LIMIT 1", (ctx.guild.id, now()))
            if season:
                cooldowns = state(self.bot)["season_message_cooldowns"]
                key = (season["id"], ctx.author.id)
                mono = time.monotonic()
                if mono - float(cooldowns.get(key, 0.0)) >= 5.0:
                    cooldowns[key] = mono
                    points = 2 if game_inc else 1
                    await conn.execute(
                        "INSERT INTO v17_season_points (season_id,user_id,points,updated_at) VALUES (?,?,?,?) "
                        "ON CONFLICT(season_id,user_id) DO UPDATE SET points=points+excluded.points,updated_at=excluded.updated_at",
                        (season["id"], ctx.author.id, points, now()),
                    )
            await conn.commit()

            daily = await self.bot.db.fetchone(
                "SELECT * FROM v17_activity_counters WHERE guild_id=? AND user_id=? AND period_kind='daily' AND period_key=?",
                (ctx.guild.id, ctx.author.id, daily_key),
            )
            unlocked = []
            if daily:
                if int(daily["commands_count"]) >= 1 and await _unlock_achievement(self.bot, ctx.guild.id, ctx.author.id, "first_command", 25):
                    unlocked.append("Première commande (+25 🪙)")
                total_commands = await self.bot.db.fetchone(
                    "SELECT COALESCE(SUM(commands_count),0) s FROM v17_activity_counters WHERE guild_id=? AND user_id=? AND period_kind='daily'",
                    (ctx.guild.id, ctx.author.id),
                )
                if int(total_commands["s"] or 0) >= 100 and await _unlock_achievement(self.bot, ctx.guild.id, ctx.author.id, "commander_100", 200):
                    unlocked.append("100 commandes (+200 🪙)")
                total_games = await self.bot.db.fetchone(
                    "SELECT COALESCE(SUM(games_count),0) s FROM v17_activity_counters WHERE guild_id=? AND user_id=? AND period_kind='daily'",
                    (ctx.guild.id, ctx.author.id),
                )
                if int(total_games["s"] or 0) >= 10 and await _unlock_achievement(self.bot, ctx.guild.id, ctx.author.id, "gamer_10", 150):
                    unlocked.append("10 mini-jeux (+150 🪙)")
            if economy_inc:
                balance = await self.bot.db.get_balance(ctx.guild.id, ctx.author.id)
                if int(balance["cash"] or 0) + int(balance["bank"] or 0) >= 1000:
                    if await _unlock_achievement(self.bot, ctx.guild.id, ctx.author.id, "wealth_1000", 100):
                        unlocked.append("1000 pièces de patrimoine (+100 🪙)")
            if unlocked:
                await ctx.send(embed=embeds.success("\n".join(f"• {item}" for item in unlocked), title="Succès débloqué"))
        except Exception:
            logger.debug("V17 : enregistrement progression impossible.", exc_info=True)


async def install(bot: commands.Bot, extension_name: str = "") -> None:
    await ensure_schema(bot)
    register_command_policy(
        public={"transactions", "achievements", "missions", "season", "gamelobby", "matchmake"},
        ai={"aimemorychannel", "airolequota", "aicontext"},
        economy={"shopstock", "shoppromo"},
    )
    if bot.get_cog("V17AIEconomyGames") is None:
        await bot.add_cog(V17AIEconomyGames(bot))
    install_ai_pipeline(bot)
    install_shop_atomic_rules(bot)
    install_economy_antifarm(bot)


__all__ = ["install"]
