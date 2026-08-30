"""Diagnostic propriétaire du pipeline de logs SentriX.

Ce module observe les événements Gateway et l'état du transport, sans monkey-patch.
``+logs-diag`` répond volontairement avec un vrai ``discord.Embed`` natif et sa sonde
passe directement par le transport V83, sans renderer de réponses de commandes.
"""
from __future__ import annotations

import os
import time
from collections import Counter

import discord
from discord.ext import commands

from utils import checks, log_service
from . import logs_runtime_v83

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


def _unwrap_send(function):
    current = function
    seen: set[int] = set()
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        original = (
            getattr(current, "_sentrix_original_send", None)
            or getattr(current, "_sentrix_original", None)
        )
        if not callable(original):
            break
        current = original
    return current


async def _native_embed_send(ctx: commands.Context, panel: discord.Embed) -> None:
    """Envoie un embed Discord classique sans passer par ctx.send ni un renderer UI."""
    native_send = _unwrap_send(discord.abc.Messageable.send)
    await native_send(
        ctx.channel,
        embed=panel,
        allowed_mentions=discord.AllowedMentions.none(),
    )


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
                enabled = bool(setting.get("enabled"))

                # Une route volontairement non configurée n'est pas une panne du transport.
                if not enabled and not channel_id:
                    lines.append(f"`{log_type}` • Non configuré")
                    continue

                valid, reason = log_service.validate_channel(
                    guild,
                    channel_id,
                    needs_file=True,
                )
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
            panel.set_footer(text="SentriX • Diagnostic logs")
            return await _native_embed_send(ctx, panel)

        state = _state(self.bot)
        logs_cog = self.bot.get_cog("Logs")
        try:
            listener_count = len(logs_cog.get_listeners()) if logs_cog is not None else 0
        except Exception:
            listener_count = 0

        instance_override = bool(logs_cog is not None and "_send" in vars(logs_cog))
        resolved_send = getattr(logs_cog, "_send", None) if logs_cog is not None else None
        resolved_func = getattr(resolved_send, "__func__", resolved_send)

        active_global = log_service.send_log
        global_is_v83 = active_global is logs_runtime_v83._traced_canonical_send_log
        global_name = (
            f"{getattr(active_global, '__module__', '?')}."
            f"{getattr(active_global, '__qualname__', '?')}"
        )

        # Embed métier minimal : la sonde doit tester le même V83 que les vrais listeners.
        probe = discord.Embed(
            title="Diagnostic live des logs",
            colour=discord.Colour.blurple(),
        )
        probe.add_field(
            name="Origine",
            value="+logs-diag • pipeline officiel Components V2",
            inline=False,
        )

        transport_ok = False
        transport_exception = None
        try:
            transport_ok = bool(await logs_runtime_v83._traced_canonical_send_log(
                self.bot,
                ctx.guild,
                "messages",
                probe,
                event_key=f"diag-v2:{ctx.guild.id}:{time.time_ns()}",
            ))
        except Exception as exc:
            transport_exception = f"{type(exc).__name__}: {exc}"[:700]

        route_lines, routes_ok = await self._route_status(ctx.guild)
        send_patched = discord.TextChannel.send is not discord.abc.Messageable.send
        healthy = bool(
            transport_ok
            and logs_cog is not None
            and listener_count > 0
            and not instance_override
            and not send_patched
            and global_is_v83
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
                else "Au moins un contrôle du pipeline des logs a échoué."
            ),
            colour=discord.Colour.green() if healthy else discord.Colour.red(),
        )

        bot_user = getattr(self.bot, "user", None)
        avatar = getattr(getattr(bot_user, "display_avatar", None), "url", None)
        if avatar:
            panel.set_thumbnail(url=str(avatar))

        panel.add_field(
            name="Transport V2",
            value=f"**{'OK' if transport_ok else 'ÉCHEC'}**",
            inline=True,
        )
        panel.add_field(
            name="Gateway",
            value=f"**{listener_count}** listeners\n**{event_total}** événements",
            inline=True,
        )
        panel.add_field(
            name="Railway",
            value=f"Service : `{service_name}`\nCommit : `{commit[:12]}`",
            inline=False,
        )
        panel.add_field(
            name="Pipeline",
            value=(
                f"SEND PATCHED : **{send_patched}**\n"
                f"Logs._send instance override : **{instance_override}**\n"
                f"Logs._send : `{getattr(resolved_func, '__module__', '?')}.{getattr(resolved_func, '__qualname__', '?')}`\n"
                f"log_service.send_log V83 : **{global_is_v83}**\n"
                f"Global : `{global_name}`"
            )[:1024],
            inline=False,
        )
        panel.add_field(
            name="Routes",
            value="\n".join(route_lines)[:1024] or "Aucune route détectée.",
            inline=False,
        )

        if transport_exception:
            panel.add_field(
                name="Erreur transport",
                value=f"```py\n{transport_exception[:900]}\n```",
                inline=False,
            )

        panel.set_footer(text="SentriX • Diagnostic Components V2")
        await _native_embed_send(ctx, panel)


async def install(bot: commands.Bot) -> None:
    existing = bot.get_cog("LogRuntimeDiagnostic")
    if existing is not None:
        await bot.remove_cog("LogRuntimeDiagnostic")
    await bot.add_cog(LogRuntimeDiagnostic(bot))


async def setup(bot: commands.Bot) -> None:
    await install(bot)
