"""Production V9: télémétrie des commandes et diagnostic santé unifié."""

import inspect
import json
import time

import discord
from discord.ext import commands, tasks

import config
from database.db import now

COG_NAME = "CommandObservabilityV9"
SLOW_SECONDS = 3.0
STUCK_SECONDS = 20.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS production_command_events_v9 (
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
CREATE INDEX IF NOT EXISTS idx_command_events_v9_time ON production_command_events_v9 (created_at);
CREATE TABLE IF NOT EXISTS production_health_snapshots_v9 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
"""
_TREE_ERROR_PATCHED = False
_SECURITY_PATCHED = False


async def _record(bot, guild_id, user_id, name, kind, duration, status, detail=""):
    await bot.db.execute(
        "INSERT INTO production_command_events_v9 "
        "(guild_id,user_id,command_name,command_kind,duration_ms,status,detail,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (guild_id, user_id, name[:120], kind, max(0, int(duration * 1000)), status, detail[:900], now()),
    )


async def _health(bot):
    problems = []
    ready = bool(bot.is_ready())
    latency = round(float(getattr(bot, "latency", 0.0) or 0.0) * 1000) if ready else None
    db_ok = False
    try:
        row = await bot.db.fetchone("SELECT 1 AS ok")
        db_ok = bool(row and int(row["ok"]) == 1)
    except Exception:
        pass
    if not ready:
        problems.append("Discord n'est pas prêt.")
    if not db_ok:
        problems.append("SQLite ne répond pas.")

    redis_state = "non_configuré"
    postgres_state = "non_configuré"
    infra = getattr(bot, "sentrix_infra", None)
    if infra is not None and hasattr(infra, "health"):
        try:
            state = infra.health()
            if inspect.isawaitable(state):
                state = await state
            if isinstance(state, dict):
                if "redis_online" in state:
                    redis_state = "ok" if state.get("redis_online") else "erreur"
                if "postgres_online" in state:
                    postgres_state = "ok" if state.get("postgres_online") else "erreur"
        except Exception:
            redis_state = postgres_state = "erreur"
    durable = getattr(bot, "sentrix_durable_store", None)
    if durable is not None and hasattr(durable, "health"):
        try:
            state = durable.health()
            if inspect.isawaitable(state):
                state = await state
            if isinstance(state, dict) and state.get("configured"):
                postgres_state = "ok" if state.get("postgres_online") else "erreur"
        except Exception:
            postgres_state = "erreur"
    if redis_state == "erreur":
        problems.append("Redis est indisponible.")
    if postgres_state == "erreur":
        problems.append("PostgreSQL durable est indisponible.")

    ai_state = "ok" if bool(getattr(config, "OPENAI_API_KEY", "")) else "non_configuré"
    try:
        circuit = await bot.db.fetchone("SELECT opened_until FROM api_circuit_state WHERE service='openai_text'")
        if circuit and int(circuit["opened_until"] or 0) > now():
            ai_state = "circuit_ouvert"
            problems.append("Le service IA est temporairement dégradé.")
    except Exception:
        pass

    actual = {str(command.name).casefold() for command in bot.tree.get_commands()}
    expected = set()
    try:
        from . import command_catalog_cleanup
        expected = set(command_catalog_cleanup.normal_direct_commands())
    except Exception:
        pass
    missing = sorted(expected - actual)
    extra = sorted(actual - expected) if expected else []
    if missing:
        problems.append("Commandes slash manquantes: " + ", ".join(missing[:8]))
    if extra:
        problems.append("Commandes slash inattendues: " + ", ".join(extra[:8]))

    cutoff = now() - 900
    counts = {}
    for key, condition in {
        "errors": "status='error'",
        "slow": "status IN ('slow','stuck')",
        "cooldowns": "status='cooldown'",
        "double_responses": "detail LIKE '%InteractionResponded%'",
    }.items():
        row = await bot.db.fetchone(
            f"SELECT COUNT(*) c FROM production_command_events_v9 WHERE created_at>=? AND {condition}",
            (cutoff,),
        )
        counts[key] = int(row["c"] or 0) if row else 0
    if counts["errors"] >= 5:
        problems.append(f"{counts['errors']} erreurs de commande en 15 minutes.")
    if counts["slow"] >= 5:
        problems.append(f"{counts['slow']} commandes lentes ou bloquées en 15 minutes.")
    if counts["double_responses"]:
        problems.append(f"{counts['double_responses']} doubles réponses Discord détectées.")

    status = "healthy"
    if not db_ok or (not ready and bool(getattr(bot, "user", None))):
        status = "unavailable"
    elif problems:
        status = "degraded"
    snapshot = {
        "status": status,
        "discord": {"ready": ready, "latency_ms": latency},
        "database": {"sqlite": "ok" if db_ok else "erreur", "postgres": postgres_state, "redis": redis_state},
        "openai": {"state": ai_state},
        "commands": {
            "prefix_roots": len(bot.commands),
            "slash_roots": len(actual),
            "expected_slash_roots": len(expected) if expected else None,
            "missing_slash": missing,
            "extra_slash": extra,
            "recent_errors": counts["errors"],
            "recent_slow_or_stuck": counts["slow"],
            "recent_cooldowns": counts["cooldowns"],
            "recent_double_responses": counts["double_responses"],
        },
        "guilds": len(bot.guilds),
        "problems": problems[:12],
        "generated_at": now(),
    }
    bot.production_v9_health_snapshot = snapshot
    await bot.db.execute(
        "INSERT INTO production_health_snapshots_v9 (status,payload_json,created_at) VALUES (?,?,?)",
        (status, json.dumps(snapshot, ensure_ascii=False), now()),
    )
    await bot.db.execute("DELETE FROM production_health_snapshots_v9 WHERE created_at<?", (now() - 7 * 86400,))
    return snapshot


class CommandObservabilityV9(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.prefix_active = {}
        self.slash_active = {}
        self.stuck_reported = set()
        self.health_loop.start()
        self.watchdog.start()

    def cog_unload(self):
        self.health_loop.cancel()
        self.watchdog.cancel()

    async def refresh_health(self):
        return await _health(self.bot)

    @tasks.loop(seconds=60)
    async def health_loop(self):
        await self.refresh_health()

    @health_loop.before_loop
    async def before_health(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=5)
    async def watchdog(self):
        current = time.monotonic()
        for kind, active in (("prefix", self.prefix_active), ("slash", self.slash_active)):
            for key, data in list(active.items()):
                started, guild_id, user_id, name = data
                if current - started < STUCK_SECONDS or (kind, key) in self.stuck_reported:
                    continue
                self.stuck_reported.add((kind, key))
                await _record(self.bot, guild_id, user_id, name, kind, current - started, "stuck", "Commande encore active après 20 secondes")

    @watchdog.before_loop
    async def before_watchdog(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_command(self, ctx):
        if not ctx.command:
            return
        key = int(getattr(ctx.message, "id", 0) or id(ctx))
        root = ctx.command.root_parent or ctx.command
        self.prefix_active[key] = (time.monotonic(), ctx.guild.id if ctx.guild else None, ctx.author.id, root.name.casefold())

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        key = int(getattr(ctx.message, "id", 0) or id(ctx))
        data = self.prefix_active.pop(key, None)
        if not data:
            return
        self.stuck_reported.discard(("prefix", key))
        started, guild_id, user_id, name = data
        duration = time.monotonic() - started
        await _record(self.bot, guild_id, user_id, name, "prefix", duration, "slow" if duration >= SLOW_SECONDS else "ok")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        key = int(getattr(getattr(ctx, "message", None), "id", 0) or id(ctx))
        data = self.prefix_active.pop(key, None)
        self.stuck_reported.discard(("prefix", key))
        if data:
            started, guild_id, user_id, name = data
            duration = time.monotonic() - started
        else:
            root = ctx.command.root_parent or ctx.command if ctx.command else None
            guild_id = ctx.guild.id if ctx.guild else None
            user_id = ctx.author.id if ctx.author else None
            name = root.name.casefold() if root else "unknown"
            duration = 0.0
        original = getattr(error, "original", error)
        if isinstance(error, commands.CommandOnCooldown):
            status = "cooldown"
        elif isinstance(error, (commands.BadArgument, commands.MissingRequiredArgument)):
            status = "usage"
        else:
            status = "error"
        await _record(self.bot, guild_id, user_id, name, "prefix", duration, status, f"{type(original).__name__}: {str(original)[:700]}")

    @commands.Cog.listener()
    async def on_interaction(self, interaction):
        if interaction.type != discord.InteractionType.application_command:
            return
        payload = interaction.data if isinstance(interaction.data, dict) else {}
        self.slash_active[int(interaction.id)] = (
            time.monotonic(), interaction.guild_id, interaction.user.id if interaction.user else None,
            str(payload.get("name") or "unknown").casefold(),
        )

    @commands.Cog.listener("on_app_command_completion")
    async def app_completion(self, interaction, command):
        key = int(interaction.id)
        data = self.slash_active.pop(key, None)
        if not data:
            return
        self.stuck_reported.discard(("slash", key))
        started, guild_id, user_id, name = data
        duration = time.monotonic() - started
        await _record(self.bot, guild_id, user_id, name, "slash", duration, "slow" if duration >= SLOW_SECONDS else "ok")


async def security_health(ctx):
    runtime = ctx.bot.get_cog(COG_NAME)
    if runtime is None:
        return await ctx.send("Diagnostic V9 indisponible.")
    state = await runtime.refresh_health()
    commands_state = state["commands"]
    database = state["database"]
    lines = [
        f"Discord: {'OK' if state['discord']['ready'] else 'ERREUR'}" + (f" • {state['discord']['latency_ms']} ms" if state['discord']['latency_ms'] is not None else ""),
        f"SQLite: {database['sqlite']} • PostgreSQL: {database['postgres']} • Redis: {database['redis']}",
        f"IA: {state['openai']['state']}",
        f"Commandes: {commands_state['prefix_roots']} préfixées • {commands_state['slash_roots']} slash",
        f"15 min: {commands_state['recent_errors']} erreur(s) • {commands_state['recent_slow_or_stuck']} lente(s)/bloquée(s) • {commands_state['recent_double_responses']} double(s) réponse(s)",
    ]
    lines.append("\nProblèmes:\n- " + "\n- ".join(state["problems"][:8]) if state["problems"] else "\nAucun problème critique détecté.")
    embed = discord.Embed(
        title=f"Diagnostic bot — {state['status']}",
        description="\n".join(lines),
        colour=discord.Colour.green() if state["status"] == "healthy" else discord.Colour.orange(),
    )
    await ctx.send(embed=embed)


def _install_security_health(bot):
    global _SECURITY_PATCHED
    if _SECURITY_PATCHED:
        return
    root = bot.get_command("security")
    if isinstance(root, commands.Group) and root.get_command("health") is None:
        root.add_command(commands.Command(security_health, name="health", help="Afficher l'état technique du bot."))
    _SECURITY_PATCHED = True


def _install_tree_errors(bot, runtime):
    global _TREE_ERROR_PATCHED
    if _TREE_ERROR_PATCHED:
        return
    current = bot.tree.on_error
    if getattr(current, "_sentrix_command_observability_v9", False):
        _TREE_ERROR_PATCHED = True
        return

    async def wrapped(interaction, error):
        key = int(interaction.id)
        data = runtime.slash_active.pop(key, None)
        runtime.stuck_reported.discard(("slash", key))
        if data:
            started, guild_id, user_id, name = data
            duration = time.monotonic() - started
        else:
            payload = interaction.data if isinstance(interaction.data, dict) else {}
            guild_id, user_id = interaction.guild_id, interaction.user.id if interaction.user else None
            name, duration = str(payload.get("name") or "unknown").casefold(), 0.0
        original = getattr(error, "original", error)
        await _record(self_bot, guild_id, user_id, name, "slash", duration, "cooldown" if "Cooldown" in type(error).__name__ else "error", f"{type(original).__name__}: {str(original)[:700]}")
        return await current(interaction, error)

    self_bot = bot
    wrapped._sentrix_command_observability_v9 = True
    bot.tree.on_error = wrapped
    _TREE_ERROR_PATCHED = True


async def setup(bot):
    conn = getattr(bot.db, "_conn", None)
    if conn is not None:
        await conn.executescript(SCHEMA)
        await conn.commit()
    runtime = CommandObservabilityV9(bot)
    await bot.add_cog(runtime)
    _install_security_health(bot)
    _install_tree_errors(bot, runtime)
    try:
        await runtime.refresh_health()
    except Exception:
        pass
