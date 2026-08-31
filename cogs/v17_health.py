"""SentriX V17 — diagnostic global et santé des commandes."""
from __future__ import annotations

import asyncio
import logging
import os
import time

import discord
from discord.ext import commands, tasks

import config
from database.db import now
from utils import checks, embeds, log_service
from .v17_shared import ensure_schema, register_command_policy, state

logger = logging.getLogger("bot.v17-health")
SLOW_COMMAND_SECONDS = 3.0
ALERT_COOLDOWN_SECONDS = 600.0
INCIDENT_WINDOW_SECONDS = 1800


def _ctx_key(ctx: commands.Context) -> int:
    interaction = getattr(ctx, "interaction", None)
    if interaction is not None:
        return int(interaction.id)
    message = getattr(ctx, "message", None)
    return int(getattr(message, "id", 0) or id(ctx))


def _technical_error(error: commands.CommandError) -> bool:
    raw = getattr(error, "original", error)
    expected = (
        commands.UserInputError,
        commands.CheckFailure,
        commands.CommandOnCooldown,
        commands.DisabledCommand,
        commands.CommandNotFound,
    )
    return not isinstance(raw, expected)


def _iter_background_loops(bot: commands.Bot):
    seen: set[int] = set()
    for cog in bot.cogs.values():
        for name in dir(cog):
            try:
                value = getattr(cog, name)
            except Exception:
                continue
            if not isinstance(value, tasks.Loop) or id(value) in seen:
                continue
            seen.add(id(value))
            yield cog, name, value


def _loop_exception(loop: tasks.Loop) -> BaseException | None:
    task = loop.get_task()
    if task is None or task.cancelled() or loop.is_running() or not task.done():
        return None
    try:
        return task.exception()
    except (asyncio.CancelledError, asyncio.InvalidStateError):
        return None
    except Exception as exc:
        return exc


async def _background_loops(bot: commands.Bot) -> tuple[int, int]:
    total = 0
    failed = 0
    for _cog, _name, loop in _iter_background_loops(bot):
        total += 1
        if _loop_exception(loop) is not None:
            failed += 1
    return total, failed


def _startup_initialisation_error(exc: BaseException | None) -> bool:
    if exc is None:
        return False
    text = f"{type(exc).__name__}: {exc}".casefold()
    return "client has not been properly initialised" in text or "please use the login method" in text


async def _recover_startup_tasks(bot: commands.Bot) -> list[str]:
    """Redémarre après READY les tâches lancées trop tôt pendant le chargement des cogs."""
    if not bot.is_ready():
        return []

    recovered: list[str] = []
    for cog, name, loop in _iter_background_loops(bot):
        exc = _loop_exception(loop)
        if not _startup_initialisation_error(exc):
            continue
        try:
            loop.start()
            recovered.append(f"{cog.__class__.__name__}.{name}")
        except RuntimeError:
            if loop.is_running():
                recovered.append(f"{cog.__class__.__name__}.{name}")
            else:
                logger.exception("Impossible de relancer la boucle %s.%s", cog.__class__.__name__, name)
        except Exception:
            logger.exception("Impossible de relancer la boucle %s.%s", cog.__class__.__name__, name)

    platform = bot.get_cog("PlatformV4")
    if platform is not None and not bool(getattr(platform, "_ready_views", False)):
        restore_task = getattr(platform, "_restore_task", None)
        restore_exc = None
        if isinstance(restore_task, asyncio.Task) and restore_task.done() and not restore_task.cancelled():
            try:
                restore_exc = restore_task.exception()
            except (asyncio.CancelledError, asyncio.InvalidStateError):
                restore_exc = None
        if restore_task is None or restore_task.done():
            if restore_task is None or _startup_initialisation_error(restore_exc):
                method = getattr(platform, "_restore_persistent_views", None)
                if callable(method):
                    try:
                        platform._restore_task = asyncio.create_task(
                            method(), name="sentrix-platform-v4-restore-ready"
                        )
                        recovered.append("PlatformV4._restore_persistent_views")
                    except Exception:
                        logger.exception("Impossible de relancer la restauration PlatformV4")

    if recovered:
        logger.warning("Tâches de fond récupérées après READY : %s", ", ".join(recovered))
    return recovered


async def _live_incidents(bot: commands.Bot, guild_id: int, loops_failed: int):
    rows = await bot.db.fetchall(
        "SELECT source,detail,created_at FROM runtime_incidents "
        "WHERE (guild_id=? OR guild_id IS NULL) AND created_at>=? "
        "ORDER BY created_at DESC LIMIT 20",
        (guild_id, int(now()) - INCIDENT_WINDOW_SECONDS),
    )
    result = []
    for row in rows:
        detail = str(row["detail"] or "")
        source = str(row["source"] or "")
        if loops_failed == 0 and (
            "Client has not been properly initialised" in detail
            or source == "background_loop_restart"
        ):
            continue
        result.append(row)
        if len(result) >= 5:
            break
    return result


async def build_health_embed(bot: commands.Bot, guild: discord.Guild) -> discord.Embed:
    started = time.perf_counter()
    db_ok = False
    db_ms = 0.0
    try:
        db_start = time.perf_counter()
        row = await bot.db.fetchone("SELECT 1 ok")
        db_ms = (time.perf_counter() - db_start) * 1000.0
        db_ok = bool(row and row["ok"] == 1)
    except Exception:
        pass

    latency_ms = max(0.0, float(getattr(bot, "latency", 0.0) or 0.0) * 1000.0)
    me = guild.me
    perms = me.guild_permissions if me else discord.Permissions.none()
    required = {
        "Voir les salons": perms.view_channel,
        "Envoyer des messages": perms.send_messages,
        "Intégrer des liens": perms.embed_links,
        "Gérer les messages": perms.manage_messages,
        "Gérer les salons": perms.manage_channels,
        "Gérer les rôles": perms.manage_roles,
        "Modérer les membres": perms.moderate_members,
        "Expulser": perms.kick_members,
        "Bannir": perms.ban_members,
        "Voir Audit Log": perms.view_audit_log,
    }
    missing = [label for label, ok in required.items() if not ok]

    open_tickets = await bot.db.fetchone(
        "SELECT COUNT(*) c FROM tickets WHERE guild_id=? AND status='ouvert'", (guild.id,)
    )
    invalid_tickets = 0
    rows = await bot.db.fetchall(
        "SELECT channel_id FROM tickets WHERE guild_id=? AND status='ouvert' LIMIT 500", (guild.id,)
    )
    for row in rows:
        if guild.get_channel(int(row["channel_id"])) is None:
            invalid_tickets += 1

    try:
        ai_settings = await __import__("utils.ai_service", fromlist=["get_settings"]).get_settings(bot, guild.id)
        ai_enabled = bool(ai_settings.get("enabled", True))
    except Exception:
        ai_enabled = False
    has_ai_key = bool(getattr(config, "OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY"))

    log_settings = await log_service.get_all_log_settings(bot, guild.id)
    enabled_logs = 0
    invalid_logs = 0
    for _category, setting in log_settings.items():
        if not setting.get("enabled"):
            continue
        enabled_logs += 1
        ok, _reason = log_service.validate_channel(guild, setting.get("channel_id"), needs_file=True)
        if not ok:
            invalid_logs += 1

    conf = await bot.db.get_guild_config(guild.id)
    config_items = {
        "Rôle modération": bool(conf and conf["mod_role"]),
        "Salon logs principal": bool(conf and conf["log_channel"]),
        "Tickets": bool(await bot.db.fetchone("SELECT 1 FROM ticket_panels_v2 WHERE guild_id=? LIMIT 1", (guild.id,))),
    }
    automod = await bot.db.get_automod(guild.id)
    active_automod = 0
    if automod:
        for key in ("antispam", "antilink", "antiinvite", "antimention", "anticaps", "antiemoji", "antiraid", "antibot", "antiaccount", "antiscam", "antinuke"):
            try:
                active_automod += 1 if automod[key] else 0
            except (KeyError, IndexError):
                pass

    loops_total, loops_failed = await _background_loops(bot)
    recent_health = await bot.db.fetchall(
        "SELECT command_name,SUM(calls) calls,SUM(errors) errors,MAX(max_ms) max_ms "
        "FROM v17_command_health WHERE guild_id=? AND hour_bucket>=? GROUP BY command_name "
        "ORDER BY errors DESC,max_ms DESC LIMIT 8",
        (guild.id, int(now() // 3600 * 3600) - 3600),
    )
    incidents = await _live_incidents(bot, guild.id, loops_failed)

    e = embeds.neutral("Diagnostic SentriX V17")
    e.add_field(name="Discord", value=f"Latence : **{latency_ms:.0f} ms**\nBot : {'● connecté' if bot.is_ready() else '○ non prêt'}", inline=True)
    e.add_field(name="Base de données", value=f"{'● OK' if db_ok else '○ Erreur'}\nLatence : **{db_ms:.1f} ms**", inline=True)
    e.add_field(name="Permissions", value="● Toutes présentes" if not missing else "Manquantes :\n" + "\n".join(f"• {x}" for x in missing[:8]), inline=False)
    e.add_field(name="Tickets", value=f"Ouverts : **{int(open_tickets['c'] if open_tickets else 0)}**\nSalons introuvables : **{invalid_tickets}**", inline=True)
    e.add_field(name="IA", value=f"Switch serveur : **{'ON' if ai_enabled else 'OFF'}**\nClé configurée : **{'oui' if has_ai_key else 'non'}**", inline=True)
    e.add_field(name="Logs", value=f"Catégories actives : **{enabled_logs}**\nConfigurations invalides : **{invalid_logs}**", inline=True)
    e.add_field(name="Configuration", value="\n".join(f"{'●' if ok else '○'} {label}" for label, ok in config_items.items()) + f"\n● Protections AutoMod actives : **{active_automod}**", inline=False)
    e.add_field(name="Tâches de fond", value=f"Boucles détectées : **{loops_total}**\nBoucles en erreur : **{loops_failed}**", inline=True)
    e.add_field(name="Modules", value=f"Cogs chargés : **{len(bot.cogs)}**\nExtensions attendues : **{getattr(bot, 'expected_extension_count', '?')}**", inline=True)
    if recent_health:
        lines = []
        for row in recent_health:
            calls = int(row["calls"] or 0)
            errors = int(row["errors"] or 0)
            lines.append(f"• `{row['command_name']}` — {calls} appel(s), {errors} erreur(s), max {float(row['max_ms'] or 0):.0f} ms")
        e.add_field(name="Commandes à surveiller (2h)", value="\n".join(lines)[:1024], inline=False)
    if incidents:
        e.add_field(
            name="Incidents runtime récents",
            value="\n".join(
                f"• `{r['source']}` — {str(r['detail'])[:120]} — <t:{r['created_at']}:R>" for r in incidents
            )[:1024],
            inline=False,
        )
    total_ms = (time.perf_counter() - started) * 1000.0
    e.set_footer(text=f"SentriX V17 • diagnostic généré en {total_ms:.0f} ms")
    return e


class V17Health(commands.Cog, name="V17Health"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await ensure_schema(self.bot)

    @commands.Cog.listener()
    async def on_ready(self):
        await asyncio.sleep(0)
        await _recover_startup_tasks(self.bot)

    async def send_report(self, ctx: commands.Context):
        if ctx.guild is None:
            return await ctx.send(embed=embeds.error("Diagnostic disponible uniquement sur un serveur."))
        e = await build_health_embed(self.bot, ctx.guild)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="healthcheck", description="Diagnostic complet de SentriX sur ce serveur.", with_app_command=False)
    @checks.is_owner_or_admin_for("configuration")
    async def healthcheck(self, ctx: commands.Context):
        await self.send_report(ctx)

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context):
        state(self.bot)["command_started"][_ctx_key(ctx)] = time.perf_counter()

    async def _record(self, ctx: commands.Context, *, error: bool, technical: bool = False):
        if ctx.guild is None or ctx.command is None:
            return
        key = _ctx_key(ctx)
        started = state(self.bot)["command_started"].pop(key, None)
        elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0) if started else 0.0
        command_name = str(ctx.command.qualified_name)[:120]
        hour_bucket = int(now() // 3600 * 3600)
        try:
            await self.bot.db.execute(
                "INSERT INTO v17_command_health (guild_id,command_name,hour_bucket,calls,errors,total_ms,max_ms) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(guild_id,command_name,hour_bucket) DO UPDATE SET "
                "calls=calls+1,errors=errors+excluded.errors,total_ms=total_ms+excluded.total_ms,max_ms=MAX(max_ms,excluded.max_ms)",
                (ctx.guild.id, command_name, hour_bucket, 1, 1 if error else 0, elapsed_ms, elapsed_ms),
            )
            if elapsed_ms >= SLOW_COMMAND_SECONDS * 1000 or technical:
                await self._maybe_alert(ctx.guild, command_name, elapsed_ms, technical)
        except Exception:
            logger.debug("V17 health : écriture métrique impossible.", exc_info=True)

    async def _maybe_alert(self, guild: discord.Guild, command_name: str, elapsed_ms: float, technical: bool):
        alert_key = (guild.id, command_name, "error" if technical else "slow")
        mono = time.monotonic()
        previous = state(self.bot)["health_alerts"].get(alert_key, 0.0)
        if mono - float(previous) < ALERT_COOLDOWN_SECONDS:
            return
        row = await self.bot.db.fetchone(
            "SELECT SUM(calls) calls,SUM(errors) errors,MAX(max_ms) max_ms FROM v17_command_health "
            "WHERE guild_id=? AND command_name=? AND hour_bucket>=?",
            (guild.id, command_name, int(now() // 3600 * 3600) - 3600),
        )
        calls = int(row["calls"] or 0) if row else 0
        errors = int(row["errors"] or 0) if row else 0
        max_ms = float(row["max_ms"] or 0) if row else 0.0
        should_alert = (technical and errors >= 3) or (max_ms >= 5000 and calls >= 2)
        if not should_alert:
            return
        state(self.bot)["health_alerts"][alert_key] = mono
        text = (
            f"Commande : `+{command_name}`\nAppels récents : **{calls}**\nErreurs : **{errors}**\n"
            f"Latence max : **{max_ms:.0f} ms**\nDernier passage : **{elapsed_ms:.0f} ms**"
        )
        logger.warning("V17 santé commande %s : %s", command_name, text.replace("\n", " | "))
        try:
            conf = await self.bot.db.get_guild_config(guild.id)
            channel_id = conf["error_channel"] if conf else None
            channel = guild.get_channel(channel_id) if channel_id else None
            if isinstance(channel, discord.TextChannel):
                await channel.send(
                    embed=embeds.warning(text, title="Santé SentriX : commande à surveiller"),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context):
        asyncio.create_task(self._record(ctx, error=False), name=f"sentrix-v17-health-ok-{_ctx_key(ctx)}")

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if ctx.command is None:
            return
        asyncio.create_task(self._record(ctx, error=True, technical=_technical_error(error)), name=f"sentrix-v17-health-error-{_ctx_key(ctx)}")


def install_diagnostic_extension(bot: commands.Bot) -> None:
    runtime = state(bot)
    command = bot.get_command("diagnostic") or bot.get_command("diagnose")
    if command is None or getattr(command.callback, "_sentrix_v17_diagnostic", False):
        return
    original = command.callback

    async def diagnostic_v17(*args, **kwargs):
        result = await original(*args, **kwargs)
        ctx = next((value for value in args if isinstance(value, commands.Context)), kwargs.get("ctx"))
        cog = bot.get_cog("V17Health")
        if isinstance(ctx, commands.Context) and cog is not None and ctx.guild is not None:
            try:
                await cog.send_report(ctx)
            except Exception:
                logger.debug("Impossible d'ajouter le diagnostic V17 à +diagnose.", exc_info=True)
        return result

    diagnostic_v17._sentrix_v17_diagnostic = True
    diagnostic_v17._sentrix_original = original
    command.callback = diagnostic_v17
    runtime["v17_diagnostic_patch"] = True


async def install(bot: commands.Bot, extension_name: str = "") -> None:
    await ensure_schema(bot)
    register_command_policy(configuration={"healthcheck"})
    if bot.get_cog("V17Health") is None:
        await bot.add_cog(V17Health(bot))
    install_diagnostic_extension(bot)


__all__ = ["build_health_embed", "install"]
