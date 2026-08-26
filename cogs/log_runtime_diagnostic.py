"""Diagnostic live propriétaire du pipeline de logs SentriX.

Il observe le Gateway, les listeners officiels et teste directement le transport V5.3.
Le diagnostic ne dépend plus de ``log_service.send_log`` car un ancien runtime pouvait
réécrire ce symbole après l'installation du correctif.
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
    """Ajoute uniquement la télémétrie autour du Logs._send V5.3."""
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
    # Réinstalle d'abord l'autorité V5.3, puis remet uniquement l'enveloppe de diagnostic.
    log_transport_v52.install(bot)
    _patch_logs_send(bot)


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

        _reassert_transport(self.bot)
        state = _state(self.bot)
        logs_cog = self.bot.get_cog("Logs")
        try:
            listener_count = len(logs_cog.get_listeners()) if logs_cog is not None else 0
        except Exception:
            listener_count = 0

        transport_embed = embeds.log_embed(
            "Diagnostic live des logs",
            fields=(("Origine", "+logs-diag • transport V5.3 direct", False),),
        )
        transport_ok = False
        transport_exception = None
        try:
            # Teste exactement la fonction branchée directement sous Logs._send.
            transport_ok = bool(await log_transport_v52.send_log_v52(
                self.bot,
                ctx.guild,
                "messages",
                transport_embed,
                event_key=f"diag-v53:{ctx.guild.id}:{time.time_ns()}",
            ))
        except Exception as exc:
            transport_exception = f"{type(exc).__name__}: {exc}"[:300]

        v5 = getattr(self.bot, "live_log_delivery_v5_state", {}) or {}
        v53 = getattr(self.bot, "log_transport_v52_state", {}) or {}
        counts = state.get("gateway_counts") or {}
        counts_text = " • ".join(
            f"{name}:{int(counts.get(name, 0))}" for name in _TRACKED
            if int(counts.get(name, 0)) > 0
        ) or "Aucun événement observé depuis ce démarrage"

        active = log_service.send_log
        active_name = f"{getattr(active, '__module__', '?')}.{getattr(active, '__name__', type(active).__name__)}"
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
            name="Transport final",
            value=(
                f"Global : `{active_name[:180]}`\n"
                f"V5.3 installé : `{bool(v53.get('installed'))}` • Logs._send direct : `{bool(v53.get('logs_send_patched'))}`\n"
                f"Dernier V5.3 : `{v53.get('last_result') or '-'}` • erreur `{v53.get('last_error') or '-'}`\n"
                f"Message : `{str(v53.get('last_error_message') or '-')[:250]}`"
            ),
            inline=False,
        )
        panel.add_field(
            name="Dernier événement réel",
            value=(
                f"Gateway : `{state.get('last_gateway_event') or 'aucun'}` • guild `{state.get('last_gateway_guild_id') or '-'}`\n"
                f"Logs._send : `{state.get('last_official_config_key') or 'aucun'}` • "
                f"résultat `{state.get('last_official_result')}` • erreur `{state.get('last_official_error') or '-'}`\n"
                f"Ancien V5 : `{v5.get('last_result') or 'aucune tentative'}`"
            ),
            inline=False,
        )
        panel.add_field(
            name="Test pipeline V5.3 direct",
            value=(
                f"**{'SUCCÈS' if transport_ok else 'ÉCHEC'}**"
                + (f" • `{transport_exception}`" if transport_exception else "")
                + (f"\nInterne : `{v53.get('last_error')}` • `{str(v53.get('last_error_message') or '-')[:300]}`" if not transport_ok else "")
            )[:1024],
            inline=False,
        )
        panel.add_field(
            name="Routes de ce serveur",
            value="\n".join(await self._route_lines(ctx.guild))[:1024],
            inline=False,
        )
        panel.set_footer(text="Modifie/supprime ensuite un message puis relance +logs-diag.")
        await ctx.send(embed=panel)


async def install(bot: commands.Bot) -> None:
    existing = bot.get_cog("LogRuntimeDiagnostic")
    if existing is not None:
        await bot.remove_cog("LogRuntimeDiagnostic")
    await bot.add_cog(LogRuntimeDiagnostic(bot))
    _reassert_transport(bot)


async def setup(bot: commands.Bot) -> None:
    await install(bot)
