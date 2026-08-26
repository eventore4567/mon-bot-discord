"""Diagnostic live propriétaire pour le pipeline de logs SentriX.

Le but n'est pas de deviner : on distingue explicitement quatre étages :
Gateway Discord -> listeners -> Logs._send -> log_service.send_log -> salon Discord.
"""
from __future__ import annotations

import os
import time
import types
from collections import Counter

import discord
from discord.ext import commands

from utils import checks, embeds, log_service

_TRACKED = (
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
    cog = bot.get_cog("Logs")
    if cog is None:
        return
    current = getattr(cog, "_send", None)
    if not callable(current) or getattr(current, "_sentrix_live_diag", False):
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
    wrapped._sentrix_original = current
    cog._send = types.MethodType(wrapped, cog)


class LogRuntimeDiagnostic(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        _patch_logs_send(self.bot)

    @commands.Cog.listener()
    async def on_ready(self):
        _patch_logs_send(self.bot)

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

    async def _route_lines(self, guild: discord.Guild) -> list[str]:
        lines: list[str] = []
        for log_type, meta in log_service.LOG_TYPES.items():
            if not meta.get("emits"):
                continue
            try:
                setting = await log_service.get_log_setting(self.bot, guild.id, log_type)
                channel_id = int(setting.get("channel_id") or 0)
                channel = guild.get_channel(channel_id) if channel_id else None
                valid, reason = log_service.validate_channel(guild, channel_id)
                status = "ON" if setting.get("enabled") else "OFF"
                channel_name = getattr(channel, "name", "absent")
                lines.append(
                    f"`{log_type:<10}` {status} • {channel_name} • "
                    f"{'OK' if valid else reason}"
                )
            except Exception as exc:
                lines.append(f"`{log_type:<10}` ERREUR • {type(exc).__name__}")
        return lines

    @commands.command(name="logs-diag", aliases=("logsdiag",), hidden=True)
    @checks.is_bot_owner()
    async def logs_diag(self, ctx: commands.Context):
        if ctx.guild is None:
            return await ctx.send(embed=embeds.warning("Utilise cette commande dans un serveur."))

        _patch_logs_send(self.bot)
        state = _state(self.bot)
        logs_cog = self.bot.get_cog("Logs")
        try:
            listener_count = len(logs_cog.get_listeners()) if logs_cog is not None else 0
        except Exception:
            listener_count = 0

        # Test du VRAI pipeline des événements, pas de send_test_log qui contourne send_log.
        transport_embed = embeds.log_embed(
            "Diagnostic live des logs",
            fields=(("Origine", "+logs-diag • pipeline réel", False),),
        )
        transport_ok = False
        transport_error = None
        try:
            transport_ok = bool(await log_service.send_log(
                self.bot,
                ctx.guild,
                "messages",
                transport_embed,
                event_key=f"diag:{ctx.guild.id}:{time.time_ns()}",
            ))
        except Exception as exc:
            transport_error = type(exc).__name__

        v5 = getattr(self.bot, "live_log_delivery_v5_state", {}) or {}
        counts = state.get("gateway_counts") or {}
        counts_text = " • ".join(
            f"{name}:{int(counts.get(name, 0))}" for name in _TRACKED
            if int(counts.get(name, 0)) > 0
        ) or "Aucun événement observé depuis ce démarrage"

        service_name = os.getenv("RAILWAY_SERVICE_NAME") or "inconnu"
        service_id = os.getenv("RAILWAY_SERVICE_ID") or "inconnu"
        commit = os.getenv("RAILWAY_GIT_COMMIT_SHA") or "inconnu"
        bot_user = getattr(self.bot, "user", None)

        panel = embeds.brand(
            "SentriX • Diagnostic live des logs",
            "Ce diagnostic vérifie le runtime qui répond réellement sur Discord.",
        )
        panel.add_field(
            name="Instance",
            value=(
                f"Service : `{service_name}`\n"
                f"Service ID : `{service_id}`\n"
                f"Commit : `{commit[:12]}`\n"
                f"Bot : `{getattr(bot_user, 'id', 'inconnu')}`"
            ),
            inline=False,
        )
        intents = self.bot.intents
        panel.add_field(
            name="Gateway / listeners",
            value=(
                f"Cog Logs : **{'présent' if logs_cog else 'ABSENT'}** • listeners : **{listener_count}**\n"
                f"Intents : guilds={intents.guilds}, messages={intents.guild_messages}, "
                f"content={intents.message_content}, members={intents.members}, voice={intents.voice_states}\n"
                f"Événements vus : {counts_text[:700]}"
            ),
            inline=False,
        )
        panel.add_field(
            name="Dernier événement réel",
            value=(
                f"Gateway : `{state.get('last_gateway_event') or 'aucun'}` • guild `{state.get('last_gateway_guild_id') or '-'}`\n"
                f"Logs._send : `{state.get('last_official_config_key') or 'aucun'}` • "
                f"résultat `{state.get('last_official_result')}` • erreur `{state.get('last_official_error') or '-'}`\n"
                f"V5 : `{v5.get('last_result') or 'aucune tentative'}` • type `{v5.get('last_log_type') or '-'}`"
            ),
            inline=False,
        )
        panel.add_field(
            name="Test pipeline réel",
            value=(
                f"**{'SUCCÈS' if transport_ok else 'ÉCHEC'}**"
                + (f" • `{transport_error}`" if transport_error else "")
                + "\nCe test passe par `log_service.send_log`, exactement comme les listeners."
            ),
            inline=False,
        )
        panel.add_field(
            name="Routes de ce serveur",
            value="\n".join(await self._route_lines(ctx.guild))[:1024],
            inline=False,
        )
        panel.set_footer(text="Après une modification/suppression de message, relance +logs-diag pour voir le chemin exact.")
        await ctx.send(embed=panel)


async def install(bot: commands.Bot) -> None:
    existing = bot.get_cog("LogRuntimeDiagnostic")
    if existing is not None:
        await bot.remove_cog("LogRuntimeDiagnostic")
    await bot.add_cog(LogRuntimeDiagnostic(bot))
    _patch_logs_send(bot)


async def setup(bot: commands.Bot) -> None:
    await install(bot)
