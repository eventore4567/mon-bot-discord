"""Bot V11 — superviseur de résilience runtime, bot-only."""
from __future__ import annotations

import logging
import time
from types import MethodType

import discord

from utils import helpers
from discord.ext import commands, tasks

from database.db import now

logger = logging.getLogger("bot.resilience-v11")
STALE_COMMAND_SECONDS = 300.0
COOLDOWN_TTL_SECONDS = 3600.0
COOLDOWN_LIMIT = 10_000
SUPERVISOR_SECONDS = 60.0
LOG_THROTTLE_SECONDS = 60.0


class BotResilienceV11(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_telemetry_error = 0.0
        self._last_health_error = 0.0

    async def cog_load(self):
        self._patch_runtime()
        if not self.supervisor.is_running():
            self.supervisor.start()
        logger.info("Bot V11 resilience active.")

    def cog_unload(self):
        self.supervisor.cancel()

    def _patch_runtime(self):
        self._patch_telemetry()
        self._patch_health()

    def _patch_telemetry(self):
        try:
            from . import command_observability_v9 as module
        except Exception:
            return
        current = module._record
        if getattr(current, "_sentrix_v11_safe", False):
            return

        async def safe_record(bot, guild_id, user_id, name, kind, duration, status, detail=""):
            try:
                return await current(bot, guild_id, user_id, name, kind, duration, status, detail)
            except Exception:
                mono = time.monotonic()
                if mono - self._last_telemetry_error >= LOG_THROTTLE_SECONDS:
                    self._last_telemetry_error = mono
                    logger.warning("V11: telemetry write failed; command kept alive.", exc_info=True)
                return None

        safe_record._sentrix_v11_safe = True
        module._record = safe_record

    def _patch_health(self):
        runtime = self.bot.get_cog("CommandObservabilityV9")
        if runtime is None:
            return
        current = runtime.refresh_health
        if getattr(current, "_sentrix_v11_safe", False):
            return

        async def safe_health(_runtime):
            try:
                return await current()
            except Exception:
                mono = time.monotonic()
                if mono - self._last_health_error >= LOG_THROTTLE_SECONDS:
                    self._last_health_error = mono
                    logger.warning("V11: health probe failed; runtime kept alive.", exc_info=True)
                previous = getattr(self.bot, "production_v9_health_snapshot", None)
                if isinstance(previous, dict):
                    state = dict(previous)
                    state["commands"] = dict(previous.get("commands") or {})
                    state["database"] = dict(previous.get("database") or {})
                    state["discord"] = dict(previous.get("discord") or {})
                    state["openai"] = dict(previous.get("openai") or {})
                    problems = list(previous.get("problems") or [])
                else:
                    state = {
                        "discord": {
                            "ready": bool(self.bot.is_ready()),
                            "latency_ms": helpers.latence_ms(self.bot),
                        },
                        "database": {"sqlite": "erreur", "postgres": "inconnu", "redis": "inconnu"},
                        "openai": {"state": "inconnu"},
                        "commands": {
                            "prefix_roots": len(self.bot.commands),
                            "slash_roots": len(self.bot.tree.get_commands()),
                            "expected_slash_roots": None,
                            "missing_slash": [],
                            "extra_slash": [],
                            "recent_errors": 0,
                            "recent_slow_or_stuck": 0,
                            "recent_cooldowns": 0,
                            "recent_double_responses": 0,
                        },
                        "guilds": len(self.bot.guilds),
                    }
                    problems = []
                note = "Diagnostic interne temporairement indisponible; Discord continue."
                if note not in problems:
                    problems.append(note)
                state["status"] = "degraded"
                state["problems"] = problems[:12]
                state["generated_at"] = now()
                self.bot.production_v9_health_snapshot = state
                return state

        safe_health._sentrix_v11_safe = True
        runtime.refresh_health = MethodType(safe_health, runtime)

    def _prune_state(self):
        mono = time.monotonic()
        v10 = self.bot.get_cog("BotV10")
        if v10 is not None:
            cooldowns = getattr(v10, "_custom_cooldowns", None)
            if isinstance(cooldowns, dict):
                cutoff = mono - COOLDOWN_TTL_SECONDS
                for key, value in list(cooldowns.items()):
                    try:
                        stale = float(value) < cutoff
                    except (TypeError, ValueError):
                        stale = True
                    if stale:
                        cooldowns.pop(key, None)
                if len(cooldowns) > COOLDOWN_LIMIT:
                    newest = sorted(cooldowns.items(), key=lambda item: float(item[1]), reverse=True)[: COOLDOWN_LIMIT // 2]
                    cooldowns.clear()
                    cooldowns.update(newest)

            joins = getattr(v10, "_join_times", None)
            if isinstance(joins, dict):
                for guild_id, queue in list(joins.items()):
                    try:
                        while queue and float(queue[0]) < mono - 90.0:
                            queue.popleft()
                        if not queue:
                            joins.pop(guild_id, None)
                    except Exception:
                        joins.pop(guild_id, None)

        obs = self.bot.get_cog("CommandObservabilityV9")
        if obs is not None:
            valid = set()
            for kind, attr in (("prefix", "prefix_active"), ("slash", "slash_active")):
                active = getattr(obs, attr, None)
                if not isinstance(active, dict):
                    continue
                for key, data in list(active.items()):
                    try:
                        started = float(data[0])
                    except (TypeError, ValueError, IndexError):
                        active.pop(key, None)
                        continue
                    if mono - started > STALE_COMMAND_SECONDS:
                        active.pop(key, None)
                    else:
                        valid.add((kind, key))
            stuck = getattr(obs, "stuck_reported", None)
            if isinstance(stuck, set):
                stuck.intersection_update(valid)

    def _restart_loops(self):
        if self.bot.is_closed():
            return
        for cog_name, attr in (
            ("CommandObservabilityV9", "health_loop"),
            ("CommandObservabilityV9", "watchdog"),
            ("BotV10", "integration_loop"),
            ("BotV10", "privacy_cleanup_loop"),
        ):
            cog = self.bot.get_cog(cog_name)
            loop = getattr(cog, attr, None) if cog else None
            if loop is None:
                continue
            try:
                if not loop.is_running():
                    loop.start()
                    logger.warning("V11 restarted critical loop %s.%s", cog_name, attr)
            except RuntimeError:
                pass
            except Exception:
                logger.warning("V11 could not restart %s.%s", cog_name, attr, exc_info=True)

    @tasks.loop(seconds=SUPERVISOR_SECONDS)
    async def supervisor(self):
        try:
            self._patch_runtime()
            self._prune_state()
            self._restart_loops()
        except Exception:
            logger.exception("V11 supervisor cycle failed; next cycle will retry.")

    @supervisor.before_loop
    async def before_supervisor(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        v10 = self.bot.get_cog("BotV10")
        if v10 is None:
            return
        joins = getattr(v10, "_join_times", None)
        if isinstance(joins, dict):
            joins.pop(guild.id, None)
        cooldowns = getattr(v10, "_custom_cooldowns", None)
        if isinstance(cooldowns, dict):
            for key in [key for key in cooldowns if key and key[0] == guild.id]:
                cooldowns.pop(key, None)


async def setup(bot: commands.Bot):
    if bot.get_cog("BotResilienceV11") is None:
        await bot.add_cog(BotResilienceV11(bot))
