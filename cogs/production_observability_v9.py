"""Production V9: observabilité des commandes et diagnostic unifié du bot."""

import inspect
import json
import logging
import time

import discord

from utils import sentrix_panels as panels
from discord.ext import commands, tasks

import config
from database.db import now

logger = logging.getLogger("bot.production-observability-v9")

COG_NAME = "ProductionObservabilityV9"
SLOW_COMMAND_SECONDS = 3.0
STUCK_COMMAND_SECONDS = 20.0
HEALTH_INTERVAL_SECONDS = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS production_command_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    command_name TEXT NOT NULL,
    command_kind TEXT NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    detail TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_production_command_metrics_time
ON production_command_metrics (created_at);
CREATE INDEX IF NOT EXISTS idx_production_command_metrics_command
ON production_command_metrics (command_name, created_at);

CREATE TABLE IF NOT EXISTS production_health_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_production_health_time
ON production_health_snapshots (created_at);
"""

_SCHEMA_READY = False
_TREE_ERROR_PATCHED = False
_SECURITY_PATCHED = False


def _root_name(command) -> str:
    if command is None:
        return "unknown"
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "unknown") or "unknown").casefold()


async def _ensure_schema(bot: commands.Bot) -> bool:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return True
    conn = getattr(getattr(bot, "db", None), "_conn", None)
    if conn is None:
        return False
    await conn.executescript(SCHEMA)
    await conn.commit()
    _SCHEMA_READY = True
    return True


async def _execute(bot, sql: str, params: tuple = ()):
    if not await _ensure_schema(bot):
        return None
    try:
        return await bot.db.execute(sql, params)
    except Exception:
        logger.exception("Écriture observabilité V9 impossible.")
        return None


async def _fetchone(bot, sql: str, params: tuple = ()):
    if not await _ensure_schema(bot):
        return None
    try:
        return await bot.db.fetchone(sql, params)
    except Exception:
        logger.debug("Lecture observabilité V9 impossible.", exc_info=True)
        return None


async def _maybe_await(value):
    return await value if inspect.isawaitable(value) else value


async def _record_metric(
    bot,
    *,
    guild_id: int | None,
    user_id: int | None,
    command_name: str,
    kind: str,
    duration: float,
    status: str,
    detail: str = "",
):
    await _execute(
        bot,
        "INSERT INTO production_command_metrics "
        "(guild_id,user_id,command_name,command_kind,duration_ms,status,detail,created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            guild_id,
            user_id,
            command_name[:120],
            kind[:20],
            max(0, int(duration * 1000)),
            status[:30],
            detail[:1000],
            now(),
        ),
    )


async def build_health_snapshot(bot: commands.Bot) -> dict:
    problems = []
    discord_ready = bool(bot.is_ready())
    latency_ms = round(float(getattr(bot, "latency", 0.0) or 0.0) * 1000) if discord_ready else None
    if not discord_ready:
        problems.append("Discord n'est pas encore prêt.")

    db_ok = False
    try:
        row = await bot.db.fetchone("SELECT 1 AS ok")
        db_ok = bool(row and int(row["ok"]) == 1)
    except Exception:
        pass
    if not db_ok:
        problems.append("La base SQLite ne répond pas.")

    redis_state = "non_configuré"
    postgres_state = "non_configuré"
    infra = getattr(bot, "sentrix_infra", None)
    if infra is not None and hasattr(infra, "health"):
        try:
            health = await _maybe_await(infra.health())
            if isinstance(health, dict):
                if "redis_online" in health:
                    redis_state = "ok" if health.get("redis_online") else "erreur"
                if "postgres_online" in health:
                    postgres_state = "ok" if health.get("postgres_online") else "erreur"
        except Exception:
            redis_state = "erreur"
            postgres_state = "erreur"

    durable = getattr(bot, "sentrix_durable_store", None)
    if durable is not None and hasattr(durable, "health"):
        try:
            state = await _maybe_await(durable.health())
            if isinstance(state, dict) and state.get("configured"):
                postgres_state = "ok" if state.get("postgres_online") else "erreur"
        except Exception:
            postgres_state = "erreur"

    if redis_state == "erreur":
        problems.append("Redis est configuré mais indisponible.")
    if postgres_state == "erreur":
        problems.append("PostgreSQL durable est configuré mais indisponible.")

    openai_configured = bool(getattr(config, "OPENAI_API_KEY", ""))
    openai_state = "ok" if openai_configured else "non_configuré"
    circuit = await _fetchone(
        bot,
        "SELECT failures,opened_until FROM api_circuit_state WHERE service='openai_text'",
    )
    if circuit and int(circuit["opened_until"] or 0) > now():
        openai_state = "circuit_ouvert"
        problems.append("Le service IA est temporairement en circuit breaker.")
    elif not openai_configured:
        problems.append("Le service IA n'est pas configuré.")

    actual_slash = {str(command.name).casefold() for command in bot.tree.get_commands()}
    expected_slash = set()
    try:
        from . import command_catalog_cleanup
        expected_slash = set(command_catalog_cleanup.normal_direct_commands())
    except Exception:
        pass
    missing = sorted(expected_slash - actual_slash)
    extra = sorted(actual_slash - expected_slash) if expected_slash else []
    if missing:
        problems.append("Commandes / manquantes: " + ", ".join(missing[:8]))
    if extra:
        problems.append("Commandes / inattendues: " + ", ".join(extra[:8]))

    cutoff = now() - 900
    queries = {
        "errors": "status='error'",
        "slow": "status IN ('slow','stuck')",
        "cooldowns": "status='cooldown'",
        "double_responses": "detail LIKE '%InteractionResponded%'",
    }
    counts = {}
    for key, where in queries.items():
        row = await _fetchone(
            bot,
            f"SELECT COUNT(*) c FROM production_command_metrics WHERE created_at>=? AND {where}",
            (cutoff,),
        )
        counts[key] = int(row["c"] or 0) if row else 0

    if counts["errors"] >= 5:
        problems.append(f"{counts['errors']} erreurs de commande sur les 15 dernières minutes.")
    if counts["slow"] >= 5:
        problems.append(f"{counts['slow']} commandes lentes ou bloquées sur les 15 dernières minutes.")
    if counts["double_responses"]:
        problems.append(f"{counts['double_responses']} doubles réponses Discord détectées récemment.")
    if counts["cooldowns"] >= 25:
        problems.append(f"{counts['cooldowns']} refus de cooldown en 15 minutes; vérification recommandée.")

    ticket_response = None
    try:
        ticket_response = await bot.db.fetchone(
            "SELECT AVG(first_response_seconds) avg_seconds,COUNT(*) c "
            "FROM ticket_service_metrics_v2 WHERE first_response_seconds IS NOT NULL AND updated_at>=?",
            (now() - 7 * 86400,),
        )
    except Exception:
        pass
    avg_response = (
        round(float(ticket_response["avg_seconds"]))
        if ticket_response and ticket_response["avg_seconds"] is not None
        else None
    )

    status = "healthy"
    if not db_ok or (not discord_ready and bool(getattr(bot, "user", None))):
        status = "unavailable"
    elif problems:
        status = "degraded"

    snapshot = {
        "status": status,
        "discord": {"ready": discord_ready, "latency_ms": latency_ms},
        "database": {
            "sqlite": "ok" if db_ok else "erreur",
            "postgres": postgres_state,
            "redis": redis_state,
        },
        "openai": {"state": openai_state, "configured": openai_configured},
        "commands": {
            "prefix_roots": len(bot.commands),
            "slash_roots": len(actual_slash),
            "expected_slash_roots": len(expected_slash) if expected_slash else None,
            "missing_slash": missing,
            "extra_slash": extra,
            "recent_errors": counts["errors"],
            "recent_slow_or_stuck": counts["slow"],
            "recent_double_responses": counts["double_responses"],
            "recent_cooldowns": counts["cooldowns"],
        },
        "tickets": {
            "avg_first_response_seconds_7d": avg_response,
            "measured_responses_7d": int(ticket_response["c"] or 0) if ticket_response else 0,
        },
        "guilds": len(bot.guilds),
        "problems": problems[:12],
        "generated_at": now(),
    }
    bot.production_v9_health_snapshot = snapshot
    await _execute(
        bot,
        "INSERT INTO production_health_snapshots (status,payload_json,created_at) VALUES (?,?,?)",
        (status, json.dumps(snapshot, ensure_ascii=False), now()),
    )
    await _execute(
        bot,
        "DELETE FROM production_health_snapshots WHERE created_at<?",
        (now() - 7 * 86400,),
    )
    return snapshot


class ProductionObservabilityV9(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._prefix_started = {}
        self._slash_started = {}
        self._stuck_reported = set()
        self.health_loop.start()
        self.stuck_watchdog.start()

    def cog_unload(self):
        self.health_loop.cancel()
        self.stuck_watchdog.cancel()

    async def refresh_health(self):
        return await build_health_snapshot(self.bot)

    @tasks.loop(seconds=HEALTH_INTERVAL_SECONDS)
    async def health_loop(self):
        await self.refresh_health()

    @health_loop.before_loop
    async def before_health_loop(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=5)
    async def stuck_watchdog(self):
        mono = time.monotonic()
        for kind, active in (("prefix", self._prefix_started), ("slash", self._slash_started)):
            for key, (started, guild_id, user_id, name) in list(active.items()):
                if mono - started < STUCK_COMMAND_SECONDS:
                    continue
                marker = (kind, key)
                if marker in self._stuck_reported:
                    continue
                self._stuck_reported.add(marker)
                await _record_metric(
                    self.bot,
                    guild_id=guild_id,
                    user_id=user_id,
                    command_name=name,
                    kind=kind,
                    duration=mono - started,
                    status="stuck",
                    detail=f"Commande toujours active après {STUCK_COMMAND_SECONDS:.0f}s",
                )

    @stuck_watchdog.before_loop
    async def before_stuck_watchdog(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context):
        if ctx.command is None:
            return
        key = int(getattr(getattr(ctx, "message", None), "id", 0) or id(ctx))
        self._prefix_started[key] = (
            time.monotonic(),
            ctx.guild.id if ctx.guild else None,
            ctx.author.id if ctx.author else None,
            _root_name(ctx.command),
        )

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context):
        key = int(getattr(getattr(ctx, "message", None), "id", 0) or id(ctx))
        data = self._prefix_started.pop(key, None)
        if not data:
            return
        self._stuck_reported.discard(("prefix", key))
        started, guild_id, user_id, name = data
        duration = time.monotonic() - started
        await _record_metric(
            self.bot,
            guild_id=guild_id,
            user_id=user_id,
            command_name=name,
            kind="prefix",
            duration=duration,
            status="slow" if duration >= SLOW_COMMAND_SECONDS else "ok",
        )

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        key = int(getattr(getattr(ctx, "message", None), "id", 0) or id(ctx))
        data = self._prefix_started.pop(key, None)
        self._stuck_reported.discard(("prefix", key))
        if data:
            started, guild_id, user_id, name = data
            duration = time.monotonic() - started
        else:
            guild_id = ctx.guild.id if ctx.guild else None
            user_id = ctx.author.id if ctx.author else None
            name = _root_name(ctx.command)
            duration = 0.0
        original = getattr(error, "original", error)
        if isinstance(error, commands.CommandOnCooldown):
            status = "cooldown"
        elif isinstance(error, (commands.BadArgument, commands.MissingRequiredArgument)):
            status = "usage"
        else:
            status = "error"
        await _record_metric(
            self.bot,
            guild_id=guild_id,
            user_id=user_id,
            command_name=name,
            kind="prefix",
            duration=duration,
            status=status,
            detail=f"{type(original).__name__}: {str(original)[:800]}",
        )

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.application_command:
            return
        payload = interaction.data if isinstance(interaction.data, dict) else {}
        self._slash_started[int(interaction.id)] = (
            time.monotonic(),
            interaction.guild_id,
            interaction.user.id if interaction.user else None,
            str(payload.get("name") or "unknown").casefold(),
        )

    @commands.Cog.listener("on_app_command_completion")
    async def app_command_completion(self, interaction: discord.Interaction, command):
        key = int(interaction.id)
        data = self._slash_started.pop(key, None)
        if not data:
            return
        self._stuck_reported.discard(("slash", key))
        started, guild_id, user_id, name = data
        duration = time.monotonic() - started
        await _record_metric(
            self.bot,
            guild_id=guild_id,
            user_id=user_id,
            command_name=name,
            kind="slash",
            duration=duration,
            status="slow" if duration >= SLOW_COMMAND_SECONDS else "ok",
        )


async def _security_health(ctx: commands.Context):
    runtime = ctx.bot.get_cog(COG_NAME)
    if runtime is None:
        return await ctx.send("Diagnostic V9 indisponible.")
    snapshot = await runtime.refresh_health()
    commands_state = snapshot["commands"]
    database = snapshot["database"]
    lines = [
        f"Discord: {'OK' if snapshot['discord']['ready'] else 'ERREUR'}"
        + (f" • {snapshot['discord']['latency_ms']} ms" if snapshot["discord"]["latency_ms"] is not None else ""),
        f"SQLite: {database['sqlite']} • PostgreSQL: {database['postgres']} • Redis: {database['redis']}",
        f"IA: {snapshot['openai']['state']}",
        f"Commandes: {commands_state['prefix_roots']} préfixées • {commands_state['slash_roots']} slash",
        (
            "15 min: "
            f"{commands_state['recent_errors']} erreur(s) • "
            f"{commands_state['recent_slow_or_stuck']} lente(s)/bloquée(s) • "
            f"{commands_state['recent_double_responses']} double(s) réponse(s) • "
            f"{commands_state['recent_cooldowns']} cooldown(s)"
        ),
    ]
    if snapshot["problems"]:
        lines.append("\nProblèmes détectés:\n- " + "\n- ".join(snapshot["problems"][:8]))
    else:
        lines.append("\nAucun problème critique détecté.")
    embed = discord.Embed(
        title=f"Diagnostic bot — {snapshot['status']}",
        description="\n".join(lines),
        colour=discord.Colour.green() if snapshot["status"] == "healthy" else discord.Colour.orange(),
    )
    await panels.envoyer(ctx, panels.depuis_embed(embed))


def _install_security_health(bot: commands.Bot):
    global _SECURITY_PATCHED
    if _SECURITY_PATCHED:
        return
    root = bot.get_command("security")
    if not isinstance(root, commands.Group):
        return
    if root.get_command("health") is None:
        root.add_command(
            commands.Command(
                _security_health,
                name="health",
                help="Diagnostic complet du bot et de ses dépendances.",
            )
        )
    _SECURITY_PATCHED = True


def _install_tree_error_metrics(bot: commands.Bot, runtime: ProductionObservabilityV9):
    global _TREE_ERROR_PATCHED
    if _TREE_ERROR_PATCHED:
        return
    tree = bot.tree
    current = tree.on_error
    if getattr(current, "_sentrix_production_v9_error_metrics", False):
        _TREE_ERROR_PATCHED = True
        return

    async def error_with_metrics(interaction: discord.Interaction, error):
        key = int(interaction.id)
        data = runtime._slash_started.pop(key, None)
        runtime._stuck_reported.discard(("slash", key))
        if data:
            started, guild_id, user_id, name = data
            duration = time.monotonic() - started
        else:
            payload = interaction.data if isinstance(interaction.data, dict) else {}
            guild_id = interaction.guild_id
            user_id = interaction.user.id if interaction.user else None
            name = str(payload.get("name") or "unknown").casefold()
            duration = 0.0
        original = getattr(error, "original", error)
        await _record_metric(
            bot,
            guild_id=guild_id,
            user_id=user_id,
            command_name=name,
            kind="slash",
            duration=duration,
            status="cooldown" if "Cooldown" in type(error).__name__ else "error",
            detail=f"{type(original).__name__}: {str(original)[:800]}",
        )
        return await current(interaction, error)

    error_with_metrics._sentrix_production_v9_error_metrics = True
    tree.on_error = error_with_metrics
    _TREE_ERROR_PATCHED = True


async def setup(bot: commands.Bot):
    await _ensure_schema(bot)
    runtime = ProductionObservabilityV9(bot)
    await bot.add_cog(runtime)
    _install_security_health(bot)
    _install_tree_error_metrics(bot, runtime)
    try:
        await runtime.refresh_health()
    except Exception:
        logger.debug("Snapshot santé initial indisponible.", exc_info=True)
