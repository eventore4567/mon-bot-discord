"""SentriX production phase runtime.

This layer is deliberately bot-only and adds no public command.  It closes the last
production gaps that are not covered by Excellence/Mastery:
- boot/crash history and clean-shutdown tracking;
- SLO sampling (event-loop lag, Discord latency, SQLite latency, RSS, task pressure);
- in-memory command latency aggregation flushed in batches instead of one write per call;
- state-change-only alerts so a degraded dependency cannot spam logs/owners;
- automatic retry/reconnect for optional PostgreSQL/Redis infrastructure;
- a safer MissingRequiredArgument message now that +help is root-only.

The runtime is idempotent because stability_runtime invokes it after every extension.
"""
from __future__ import annotations

import asyncio
import logging
import os
import resource
import time
import uuid
from collections import defaultdict
from types import MethodType

import discord
from discord.ext import commands, tasks

from database.db import now
from utils import embeds

logger = logging.getLogger("bot.production-phase")
_COG_NAME = "ProductionPhaseRuntime"

MONITOR_INTERVAL_SECONDS = 60.0
SAMPLE_INTERVAL_SECONDS = 300
INFRA_RECOVERY_INTERVAL_SECONDS = 300

LOOP_LAG_WARN_MS = float(os.getenv("SENTRIX_LOOP_LAG_WARN_MS", "1500") or 1500)
DISCORD_LATENCY_WARN_MS = float(os.getenv("SENTRIX_DISCORD_LATENCY_WARN_MS", "1200") or 1200)
DB_LATENCY_WARN_MS = float(os.getenv("SENTRIX_DB_LATENCY_WARN_MS", "500") or 500)
TASK_PRESSURE_WARN = int(os.getenv("SENTRIX_TASK_PRESSURE_WARN", "1200") or 1200)

RUNTIME_SCHEMA = """
CREATE TABLE IF NOT EXISTS production_boots (
    boot_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    commit_sha TEXT,
    started_at INTEGER NOT NULL,
    stopped_at INTEGER,
    clean_shutdown INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_production_boots_time
ON production_boots (started_at DESC);

CREATE TABLE IF NOT EXISTS production_slo_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_lag_ms REAL NOT NULL DEFAULT 0,
    discord_latency_ms REAL NOT NULL DEFAULT 0,
    db_latency_ms REAL NOT NULL DEFAULT 0,
    rss_mb REAL NOT NULL DEFAULT 0,
    pending_tasks INTEGER NOT NULL DEFAULT 0,
    postgres_ok INTEGER NOT NULL DEFAULT 0,
    redis_ok INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_production_slo_samples_time
ON production_slo_samples (created_at DESC);

CREATE TABLE IF NOT EXISTS production_slo_state (
    key TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    detail TEXT,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS production_command_metrics (
    hour_bucket INTEGER NOT NULL,
    command_name TEXT NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    total_ms REAL NOT NULL DEFAULT 0,
    max_ms REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (hour_bucket, command_name)
);
"""


def _session_started(bot: commands.Bot) -> bool:
    return bool(getattr(getattr(bot, "http", None), "token", None))


async def _ensure_schema(bot: commands.Bot) -> bool:
    if getattr(bot, "_sentrix_production_phase_schema", False):
        return True
    conn = getattr(getattr(bot, "db", None), "_conn", None)
    if conn is None:
        return False
    await conn.executescript(RUNTIME_SCHEMA)
    await conn.commit()
    bot._sentrix_production_phase_schema = True
    return True


def _mode() -> str:
    return "canary" if os.getenv("SENTRIX_CANARY_MODE", "").strip().casefold() in {"1", "true", "yes", "on"} else "production"


def _commit_sha() -> str:
    return (
        os.getenv("RAILWAY_GIT_COMMIT_SHA")
        or os.getenv("GITHUB_SHA")
        or os.getenv("SOURCE_COMMIT")
        or ""
    )[:80]


async def _record_boot(bot: commands.Bot) -> str | None:
    if not await _ensure_schema(bot):
        return None
    existing = getattr(bot, "_sentrix_production_boot_id", None)
    if existing:
        return str(existing)
    boot_id = uuid.uuid4().hex
    await bot.db.execute(
        "INSERT INTO production_boots (boot_id,mode,commit_sha,started_at,clean_shutdown) VALUES (?,?,?,?,0)",
        (boot_id, _mode(), _commit_sha(), now()),
    )
    # Keep a bounded history; old rows are diagnostics, not business data.
    await bot.db.execute(
        "DELETE FROM production_boots WHERE boot_id IN ("
        "SELECT boot_id FROM production_boots ORDER BY started_at DESC LIMIT -1 OFFSET 100)"
    )
    bot._sentrix_production_boot_id = boot_id
    return boot_id


async def _mark_clean_shutdown(bot: commands.Bot) -> None:
    boot_id = getattr(bot, "_sentrix_production_boot_id", None)
    if not boot_id:
        return
    try:
        if await _ensure_schema(bot):
            await bot.db.execute(
                "UPDATE production_boots SET stopped_at=?, clean_shutdown=1 WHERE boot_id=?",
                (now(), str(boot_id)),
            )
    except Exception:
        logger.debug("Impossible de marquer l'arrêt production comme propre.", exc_info=True)


def _install_close_guard(bot: commands.Bot) -> None:
    current = bot.close
    function = getattr(current, "__func__", current)
    if getattr(function, "_sentrix_production_close", False):
        return

    async def close_with_production_state(_bot, *args, **kwargs):
        await _mark_clean_shutdown(_bot)
        return await current(*args, **kwargs)

    close_with_production_state._sentrix_production_close = True
    bot.close = MethodType(close_with_production_state, bot)


def _install_missing_argument_help(bot: commands.Bot) -> None:
    current = bot.on_command_error
    function = getattr(current, "__func__", current)
    if getattr(function, "_sentrix_root_help_error", False):
        return

    async def production_command_error(_bot, ctx: commands.Context, error: commands.CommandError):
        raw = getattr(error, "original", error)
        if isinstance(raw, commands.MissingRequiredArgument):
            command = getattr(ctx, "command", None)
            signature = str(getattr(command, "signature", "") or "").strip()
            prefix = str(getattr(ctx, "clean_prefix", None) or "+")
            qualified = str(getattr(command, "qualified_name", "commande") or "commande")
            usage = f"{prefix}{qualified} {signature}".strip()
            return await ctx.send(
                embed=embeds.error(
                    f"L'argument **{raw.param.name}** est obligatoire.\nSyntaxe correcte : `{usage}`\nOuvrez `{prefix}help` puis utilisez **Rechercher** pour voir les détails de la commande."
                )
            )
        return await current(ctx, error)

    production_command_error._sentrix_root_help_error = True
    bot.on_command_error = MethodType(production_command_error, bot)


class ProductionPhaseRuntime(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_tick = time.monotonic()
        self._last_sample_write = 0.0
        self._last_infra_recovery = 0.0
        self._command_buffer: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        if _session_started(bot):
            self.monitor.start()

    def cog_unload(self) -> None:
        self.monitor.cancel()

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context) -> None:
        setattr(ctx, "_sentrix_phase_started", time.perf_counter())

    def _collect_command(self, ctx: commands.Context, *, error: bool) -> None:
        command = getattr(ctx, "command", None)
        if command is None:
            return
        started = getattr(ctx, "_sentrix_phase_started", None)
        elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0) if started else 0.0
        key = str(command.qualified_name)[:120]
        row = self._command_buffer[key]
        row[0] += 1.0
        row[1] += 1.0 if error else 0.0
        row[2] += elapsed_ms
        row[3] = max(row[3], elapsed_ms)

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context) -> None:
        self._collect_command(ctx, error=False)

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, _error: commands.CommandError) -> None:
        self._collect_command(ctx, error=True)

    async def _flush_command_metrics(self) -> None:
        if not self._command_buffer or not await _ensure_schema(self.bot):
            return
        snapshot = dict(self._command_buffer)
        self._command_buffer.clear()
        hour_bucket = int(now() // 3600 * 3600)
        for command_name, values in snapshot.items():
            calls, errors, total_ms, max_ms = values
            await self.bot.db.execute(
                "INSERT INTO production_command_metrics "
                "(hour_bucket,command_name,calls,errors,total_ms,max_ms) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(hour_bucket,command_name) DO UPDATE SET "
                "calls=calls+excluded.calls, errors=errors+excluded.errors, "
                "total_ms=total_ms+excluded.total_ms, max_ms=MAX(max_ms,excluded.max_ms)",
                (hour_bucket, command_name, int(calls), int(errors), float(total_ms), float(max_ms)),
            )
        # Seven days of hourly aggregates are enough for live diagnostics.
        await self.bot.db.execute(
            "DELETE FROM production_command_metrics WHERE hour_bucket < ?",
            (int(now() - 7 * 86400),),
        )

    async def _set_state(self, key: str, status: str, detail: str) -> None:
        if not await _ensure_schema(self.bot):
            return
        previous = await self.bot.db.fetchone(
            "SELECT status,detail FROM production_slo_state WHERE key=?", (key,)
        )
        previous_status = str(previous["status"]) if previous else None
        if previous_status == status:
            return
        await self.bot.db.execute(
            "INSERT INTO production_slo_state (key,status,detail,updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET status=excluded.status, detail=excluded.detail, updated_at=excluded.updated_at",
            (key[:80], status[:20], detail[:700], now()),
        )
        if status == "degraded":
            logger.warning("SLO dégradé [%s] : %s", key, detail)
        elif previous_status == "degraded":
            logger.info("SLO rétabli [%s] : %s", key, detail)

    async def _infra_health(self) -> dict:
        infra = getattr(self.bot, "sentrix_infra", None)
        if infra is None or not hasattr(infra, "health"):
            return {
                "postgres_configured": bool(os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")),
                "postgres_online": False,
                "redis_configured": bool(os.getenv("REDIS_URL")),
                "redis_online": False,
            }
        try:
            return dict(await asyncio.wait_for(infra.health(), timeout=8.0))
        except Exception as exc:
            return {
                "postgres_configured": bool(getattr(infra, "postgres_url", "")),
                "postgres_online": False,
                "redis_configured": bool(getattr(infra, "redis_url", "")),
                "redis_online": False,
                "error": f"{type(exc).__name__}: {exc}"[:300],
            }

    async def _recover_infra_if_needed(self, state: dict) -> dict:
        configured_down = (
            bool(state.get("postgres_configured")) and not bool(state.get("postgres_online"))
        ) or (
            bool(state.get("redis_configured")) and not bool(state.get("redis_online"))
        )
        if not configured_down:
            return state
        moment = time.monotonic()
        if moment - self._last_infra_recovery < INFRA_RECOVERY_INTERVAL_SECONDS:
            return state
        self._last_infra_recovery = moment
        infra = getattr(self.bot, "sentrix_infra", None)
        reconnect = getattr(infra, "reconnect", None)
        if not callable(reconnect):
            return state
        try:
            await asyncio.wait_for(reconnect(), timeout=30.0)
            recovered = await self._infra_health()
            logger.info("Tentative de récupération automatique PostgreSQL/Redis terminée.")
            return recovered
        except Exception:
            logger.warning("Récupération automatique PostgreSQL/Redis impossible.", exc_info=True)
            return state

    async def _sample(self) -> None:
        current = time.monotonic()
        expected = self._last_tick + MONITOR_INTERVAL_SECONDS
        loop_lag_ms = max(0.0, (current - expected) * 1000.0)
        self._last_tick = current

        discord_latency_ms = max(0.0, float(getattr(self.bot, "latency", 0.0) or 0.0) * 1000.0)
        db_started = time.perf_counter()
        db_ok = True
        try:
            row = await asyncio.wait_for(self.bot.db.fetchone("SELECT 1 AS ok"), timeout=3.0)
            db_ok = bool(row)
        except Exception:
            db_ok = False
        db_latency_ms = (time.perf_counter() - db_started) * 1000.0

        # ru_maxrss is KiB on Linux (Railway). It is bytes on macOS, but the monitor only
        # runs in the deployed service; the CI never starts this task.
        try:
            rss_mb = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0
        except Exception:
            rss_mb = 0.0
        pending_tasks = sum(1 for task in asyncio.all_tasks() if not task.done())

        infra_state = await self._infra_health()
        infra_state = await self._recover_infra_if_needed(infra_state)
        pg_ok = bool(infra_state.get("postgres_online"))
        redis_ok = bool(infra_state.get("redis_online"))

        await self._set_state(
            "event_loop",
            "degraded" if loop_lag_ms > LOOP_LAG_WARN_MS else "healthy",
            f"lag={loop_lag_ms:.0f}ms seuil={LOOP_LAG_WARN_MS:.0f}ms",
        )
        await self._set_state(
            "discord",
            "degraded" if discord_latency_ms > DISCORD_LATENCY_WARN_MS else "healthy",
            f"latence={discord_latency_ms:.0f}ms seuil={DISCORD_LATENCY_WARN_MS:.0f}ms",
        )
        await self._set_state(
            "sqlite",
            "degraded" if (not db_ok or db_latency_ms > DB_LATENCY_WARN_MS) else "healthy",
            f"ok={db_ok} latence={db_latency_ms:.1f}ms seuil={DB_LATENCY_WARN_MS:.0f}ms",
        )
        await self._set_state(
            "task_pressure",
            "degraded" if pending_tasks > TASK_PRESSURE_WARN else "healthy",
            f"taches={pending_tasks} seuil={TASK_PRESSURE_WARN}",
        )
        if infra_state.get("postgres_configured"):
            await self._set_state("postgres", "healthy" if pg_ok else "degraded", f"online={pg_ok}")
        if infra_state.get("redis_configured"):
            await self._set_state("redis", "healthy" if redis_ok else "degraded", f"online={redis_ok}")

        if current - self._last_sample_write >= SAMPLE_INTERVAL_SECONDS and await _ensure_schema(self.bot):
            self._last_sample_write = current
            await self.bot.db.execute(
                "INSERT INTO production_slo_samples "
                "(loop_lag_ms,discord_latency_ms,db_latency_ms,rss_mb,pending_tasks,postgres_ok,redis_ok,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    loop_lag_ms,
                    discord_latency_ms,
                    db_latency_ms,
                    rss_mb,
                    pending_tasks,
                    1 if pg_ok else 0,
                    1 if redis_ok else 0,
                    now(),
                ),
            )
            await self.bot.db.execute(
                "DELETE FROM production_slo_samples WHERE created_at < ?",
                (now() - 30 * 86400,),
            )

    @tasks.loop(seconds=MONITOR_INTERVAL_SECONDS)
    async def monitor(self) -> None:
        try:
            await self._flush_command_metrics()
            await self._sample()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Cycle de supervision production impossible.")

    @monitor.before_loop
    async def before_monitor(self) -> None:
        await self.bot.wait_until_ready()
        self._last_tick = time.monotonic()


async def install(bot: commands.Bot, _extension_name: str | None = None) -> None:
    """Install or refresh the production hardening layer without adding commands."""
    await _ensure_schema(bot)
    await _record_boot(bot)
    _install_close_guard(bot)
    _install_missing_argument_help(bot)
    if bot.get_cog(_COG_NAME) is None:
        await bot.add_cog(ProductionPhaseRuntime(bot))
        logger.info("Phase production active : SLO, boot tracking, métriques et auto-récupération.")
