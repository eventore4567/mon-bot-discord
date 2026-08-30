"""Diagnostic propriétaire du pipeline de logs SentriX.

Ce module observe les événements Gateway et l'état du transport, mais ne monkey-patch
aucune méthode Discord ni ``Logs._send``. La sonde passe par le pipeline officiel V2.
"""
from __future__ import annotations

import os
import time
from collections import Counter

import discord
from discord.ext import commands

from utils import checks, embeds, log_service

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


class LogRuntimeDiagnostic(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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
            return await ctx.send(
                embed=embeds.error("Utilise cette commande dans un serveur.", title="Diagnostic logs")
            )

        state = _state(self.bot)
        logs_cog = self.bot.get_cog("Logs")
        try:
            listener_count = len(logs_cog.get_listeners()) if logs_cog is not None else 0
        except Exception:
            listener_count = 0

        instance_override = bool(logs_cog is not None and "_send" in vars(logs_cog))
        resolved_send = getattr(logs_cog, "_send", None) if logs_cog is not None else None
        resolved_func = getattr(resolved_send, "__func__", resolved_send)

        probe = embeds.log_embed(
            "Diagnostic live des logs",
            fields=(("Origine", "+logs-diag • pipeline officiel Components V2", False),),
        )
        transport_ok = False
        transport_exception = None
        try:
            transport_ok = bool(await log_service.send_log(
                self.bot,
                ctx.guild,
                "messages",
                probe,
                event_key=f"diag-v2:{ctx.guild.id}:{time.time_ns()}",
            ))
        except Exception as exc:
            transport_exception = f"{type(exc).__name__}: {exc}"[:300]

        route_lines, routes_ok = await self._route_status(ctx.guild)
        send_patched = discord.TextChannel.send is not discord.abc.Messageable.send
        healthy = bool(
            transport_ok
            and logs_cog is not None
            and listener_count > 0
            and not instance_override
            and not send_patched
            and routes_ok
        )

        service_name = os.getenv("RAILWAY_SERVICE_NAME") or "inconnu"
        commit = os.getenv("RAILWAY_GIT_COMMIT_SHA") or "inconnu"
        counts = state.get("gateway_counts") or {}
        event_total = sum(int(counts.get(name, 0)) for name in _TRACKED)

        panel = discord.Embed(
            title="Diagnostic logs — OK" if healthy else "Diagnostic logs — Problème détecté",
            description=(
                "Le pipeline Components V2 est l'unique transport actif."
                if healthy
                else "Une ancienne couche ou une route invalide est encore détectée."
            ),
            colour=discord.Colour.green() if healthy else discord.Colour.red(),
        )
        panel.add_field(
            name="Transport",
            value=(
                f"Probe V2 : **{'OK' if transport_ok else 'ÉCHEC'}**\n"
                f"SEND PATCHED : **{send_patched}**\n"
                f"Logs._send instance override : **{instance_override}**\n"
                f"Résolu : `{getattr(resolved_func, '__module__', '?')}.{getattr(resolved_func, '__qualname__', '?')}`"
            ),
            inline=False,
        )
        panel.add_field(
            name="Gateway",
            value=f"Listeners Logs : **{listener_count}** • Événements observés : **{event_total}**",
            inline=False,
        )
        panel.add_field(
            name="Instance Railway",
            value=f"Service : `{service_name}`\nCommit : `{commit[:12]}`",
            inline=False,
        )
        panel.add_field(
            name="Routes",
            value="\n".join(route_lines)[:1024],
            inline=False,
        )

        if transport_exception:
            panel.add_field(name="Erreur transport", value=f"`{transport_exception}`", inline=False)

        panel.set_footer(text="SentriX • Diagnostic Components V2")
        await ctx.send(embed=panel, allowed_mentions=discord.AllowedMentions.none())


async def install(bot: commands.Bot) -> None:
    existing = bot.get_cog("LogRuntimeDiagnostic")
    if existing is not None:
        await bot.remove_cog("LogRuntimeDiagnostic")
    await bot.add_cog(LogRuntimeDiagnostic(bot))


async def setup(bot: commands.Bot) -> None:
    await install(bot)
