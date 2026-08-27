"""Diagnostic propriétaire compact du pipeline de logs SentriX.

Le diagnostic observe le Gateway et teste directement le transport V5.3. Sa réponse
finale contourne volontairement les renderers globaux de commandes afin qu'un diagnostic
sain conserve toujours son embed natif compact.
"""
from __future__ import annotations

import os
import time
import types
from collections import Counter

import discord
from discord.ext import commands

from utils import checks, embeds, log_service
from . import log_transport_v52

_TRACKED = (
    "message",
    "message_edit",
    "message_delete",
    "raw_message_delete",
    "member_join",
    "member_remove",
    "role_create",
    "role_delete",
    "channel_create",
    "channel_delete",
    "voice_state_update",
)


def _state(bot: commands.Bot) -> dict:
    state = getattr(bot, "log_runtime_diagnostic_state", None)
    if not isinstance(state, dict):
        state = {
            "gateway_counts": Counter(),
            "last_gateway_event": None,
            "last_gateway_guild_id": None,
            "last_gateway_at": None,
            "official_attempts": 0,
            "last_official_config_key": None,
            "last_official_result": None,
            "last_official_error": None,
            "last_official_at": None,
        }
        bot.log_runtime_diagnostic_state = state
    return state


def _guild_id_from_args(*items) -> int | None:
    for item in items:
        guild = getattr(item, "guild", None)
        if guild is not None:
            return int(guild.id)
        guild_id = getattr(item, "guild_id", None)
        if guild_id:
            return int(guild_id)
    return None


def _seen(bot: commands.Bot, event: str, *items) -> None:
    state = _state(bot)
    counts = state.get("gateway_counts")
    if not isinstance(counts, Counter):
        counts = Counter(counts or {})
        state["gateway_counts"] = counts
    counts[event] += 1
    state["last_gateway_event"] = event
    state["last_gateway_guild_id"] = _guild_id_from_args(*items)
    state["last_gateway_at"] = int(time.time())


def _patch_logs_send(bot: commands.Bot) -> None:
    """Ajoute seulement la télémétrie autour du Logs._send V5.3."""
    cog = bot.get_cog("Logs")
    if cog is None:
        return
    current = getattr(cog, "_send", None)
    function = getattr(current, "__func__", current)
    if not callable(current) or getattr(function, "_sentrix_live_diag", False):
        return

    async def wrapped(_self, guild, config_key, embed, *, view=None, event_key=None):
        state = _state(bot)
        state["official_attempts"] = int(state.get("official_attempts") or 0) + 1
        state["last_official_config_key"] = str(config_key)
        state["last_official_result"] = None
        state["last_official_error"] = None
        state["last_official_at"] = int(time.time())
        try:
            result = await current(guild, config_key, embed, view=view, event_key=event_key)
            state["last_official_result"] = bool(result)
            return result
        except Exception as exc:
            state["last_official_error"] = type(exc).__name__
            raise

    wrapped._sentrix_live_diag = True
    wrapped._sentrix_original = function
    cog._send = types.MethodType(wrapped, cog)


def _reassert_transport(bot: commands.Bot) -> None:
    log_transport_v52.install(bot)
    _patch_logs_send(bot)


async def _native_embed_send(ctx: commands.Context, panel: discord.Embed) -> None:
    """Envoie le diagnostic sans aucun renderer de commande SentriX."""
    native_send = log_transport_v52._unwrap_messageable_send()
    kwargs = {
        "embed": panel,
        "allowed_mentions": discord.AllowedMentions.none(),
    }
    if getattr(ctx, "message", None) is not None:
        kwargs["reference"] = discord.MessageReference(
            message_id=ctx.message.id,
            channel_id=ctx.channel.id,
            guild_id=ctx.guild.id if ctx.guild else None,
            fail_if_not_exists=False,
        )
        kwargs["mention_author"] = False
    await native_send(ctx.channel, **kwargs)


class LogRuntimeDiagnostic(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        _reassert_transport(self.bot)

    @commands.Cog.listener()
    async def on_ready(self):
        _reassert_transport(self.bot)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is not None:
            _seen(self.bot, "message", message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        _seen(self.bot, "message_edit", after)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        _seen(self.bot, "message_delete", message)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        _seen(self.bot, "raw_message_delete", payload)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        _seen(self.bot, "member_join", member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        _seen(self.bot, "member_remove", member)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        _seen(self.bot, "role_create", role)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        _seen(self.bot, "role_delete", role)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        _seen(self.bot, "channel_create", channel)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        _seen(self.bot, "channel_delete", channel)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        _seen(self.bot, "voice_state_update", member)

    async def _route_status(self, guild: discord.Guild) -> tuple[list[str], bool]:
        lines: list[str] = []
        all_ok = True
        for log_type, meta in log_service.LOG_TYPES.items():
            if not meta.get("emits"):
                continue
            try:
                setting = await log_service.get_log_setting(self.bot, guild.id, log_type)
                channel_id = int(setting.get("channel_id") or 0)
                channel = guild.get_channel(channel_id) if channel_id else None
                valid, reason = log_service.validate_channel(guild, channel_id)
                enabled = bool(setting.get("enabled"))
                ok = enabled and valid and channel is not None
                all_ok = all_ok and ok
                channel_name = getattr(channel, "name", "absent")
                lines.append(
                    f"`{log_type}` • {'OK' if ok else 'À vérifier'} • {channel_name}"
                    + (f" ({reason})" if not valid else "")
                )
            except Exception as exc:
                all_ok = False
                lines.append(f"`{log_type}` • {type(exc).__name__}")
        return lines, all_ok

    @commands.command(name="logs-diag", aliases=("logsdiag",), hidden=True)
    @checks.is_bot_owner()
    async def logs_diag(self, ctx: commands.Context):
        if ctx.guild is None:
            panel = discord.Embed(
                title="Diagnostic logs",
                description="Utilise cette commande dans un serveur.",
                colour=discord.Colour.orange(),
            )
            return await _native_embed_send(ctx, panel)

        _reassert_transport(self.bot)
        state = _state(self.bot)
        logs_cog = self.bot.get_cog("Logs")
        try:
            listener_count = len(logs_cog.get_listeners()) if logs_cog is not None else 0
        except Exception:
            listener_count = 0

        probe = embeds.log_embed(
            "Diagnostic live des logs",
            fields=(("Origine", "+logs-diag • transport V5.3 direct", False),),
        )
        transport_ok = False
        transport_exception = None
        try:
            transport_ok = bool(await log_transport_v52.send_log_v52(
                self.bot,
                ctx.guild,
                "messages",
                probe,
                event_key=f"diag-v53:{ctx.guild.id}:{time.time_ns()}",
            ))
        except Exception as exc:
            transport_exception = f"{type(exc).__name__}: {exc}"[:300]

        v53 = getattr(self.bot, "log_transport_v52_state", {}) or {}
        route_lines, routes_ok = await self._route_status(ctx.guild)
        healthy = bool(
            transport_ok
            and logs_cog is not None
            and listener_count > 0
            and v53.get("installed")
            and v53.get("logs_send_patched")
            and routes_ok
        )

        service_name = os.getenv("RAILWAY_SERVICE_NAME") or "inconnu"
        commit = os.getenv("RAILWAY_GIT_COMMIT_SHA") or "inconnu"
        counts = state.get("gateway_counts") or {}
        event_total = sum(int(counts.get(name, 0)) for name in _TRACKED)

        panel = discord.Embed(
            title="Diagnostic logs — OK" if healthy else "Diagnostic logs — Problème détecté",
            description=(
                "Le pipeline des logs fonctionne normalement."
                if healthy
                else "Un composant du pipeline demande encore une vérification."
            ),
            colour=discord.Colour.green() if healthy else discord.Colour.red(),
        )
        panel.add_field(
            name="État",
            value=(
                f"Transport V5.3 : **{'OK' if transport_ok else 'ÉCHEC'}**\n"
                f"Logs._send direct : **{'OK' if v53.get('logs_send_patched') else 'NON'}**\n"
                f"Listeners : **{listener_count}** • Événements observés : **{event_total}**"
            ),
            inline=False,
        )
        panel.add_field(
            name="Instance",
            value=f"Service : `{service_name}`\nCommit : `{commit[:12]}`",
            inline=False,
        )
        panel.add_field(
            name="Routes",
            value="\n".join(route_lines)[:1024],
            inline=False,
        )

        if not healthy:
            detail = (
                transport_exception
                or str(v53.get("last_error_message") or v53.get("last_error") or "Cause non identifiée")
            )
            panel.add_field(name="Détail", value=f"`{detail[:900]}`", inline=False)

        panel.set_footer(text="SentriX • Diagnostic propriétaire des logs")
        await _native_embed_send(ctx, panel)


async def install(bot: commands.Bot) -> None:
    existing = bot.get_cog("LogRuntimeDiagnostic")
    if existing is not None:
        await bot.remove_cog("LogRuntimeDiagnostic")
    await bot.add_cog(LogRuntimeDiagnostic(bot))
    _reassert_transport(bot)


async def setup(bot: commands.Bot) -> None:
    await install(bot)
