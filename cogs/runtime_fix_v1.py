"""Correctif runtime final pour le rendu des commandes et la livraison des logs SentriX.

Ce module est volontairement charge en DERNIER par ``plain_text_all_extension``.
Il corrige deux problemes de production qui ne pouvaient pas etre resolus uniquement en
modifiant les renderers :

1. ``final_interaction_policy.install(bot)`` existait mais n'etait jamais appele par le
   runtime Railway. Le transport officiel des embeds est maintenant installe ici.
2. Les anciens salons de logs vivent dans ``guild_config`` alors que le nouveau transport
   lit ``log_settings``. Les deux sources sont resynchronisees sans ecraser une vraie
   desactivation administrateur possedant deja un salon valide.

Quand un administrateur relance ``+create-logs`` / ``/create-logs`` ou ``+create-server``,
la demande est explicite : tous les types historiques disposant d'un salon sont alors
resynchronises ET actives.
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from . import final_interaction_policy
from .configuration import Configuration, LOG_CHANNEL_DEFINITIONS
from .server_builder import ServerBuilder
from utils import log_service

logger = logging.getLogger("bot.runtime-fix-v1")

LEGACY_TO_LOG_TYPE = {
    "log_messages": "messages",
    "log_members": "members",
    "log_roles": "roles",
    "log_server": "server",
    "log_voice": "voice",
    "log_moderation": "moderation",
    "log_automod": "automod",
    "ticket_log_channel": "tickets",
}


def _configured_channel_id(conf, column: str) -> int | None:
    if not conf:
        return None
    try:
        value = conf[column]
    except (KeyError, IndexError, TypeError):
        value = None
    if not value and column != "ticket_log_channel":
        try:
            value = conf["log_channel"]
        except (KeyError, IndexError, TypeError):
            value = None
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


async def _repair_bot_permissions(guild: discord.Guild, channel_id: int) -> bool:
    """Donne au bot les permissions necessaires aux grands embeds de logs."""
    channel = guild.get_channel(int(channel_id))
    me = guild.me
    if not isinstance(channel, discord.TextChannel) or me is None:
        return False

    perms = channel.permissions_for(me)
    if (
        perms.view_channel
        and perms.send_messages
        and perms.embed_links
        and perms.read_message_history
        and perms.attach_files
    ):
        return True

    # Si le bot peut administrer le salon, on repare l'overwrite directement. Sinon on
    # laisse validate_channel expliquer precisement la permission manquante.
    if not (perms.manage_channels or me.guild_permissions.manage_channels or me.guild_permissions.administrator):
        return False

    overwrite = channel.overwrites_for(me)
    overwrite.view_channel = True
    overwrite.send_messages = True
    overwrite.embed_links = True
    overwrite.read_message_history = True
    overwrite.attach_files = True
    try:
        await channel.set_permissions(
            me,
            overwrite=overwrite,
            reason="Reparation automatique du transport des logs SentriX",
        )
        return True
    except (discord.Forbidden, discord.HTTPException):
        logger.exception("Impossible de reparer les permissions du salon de logs %s.", channel_id)
        return False


async def repair_guild_logs(
    bot: commands.Bot,
    guild: discord.Guild,
    *,
    force_enable: bool = False,
) -> dict[str, int]:
    """Resynchronise guild_config -> log_settings et repare les salons encore valides."""
    stats = {"seen": 0, "routed": 0, "enabled": 0, "permissions": 0}
    conf = await bot.db.get_guild_config(guild.id)
    if not conf:
        return stats

    for legacy_column, log_type in LEGACY_TO_LOG_TYPE.items():
        legacy_channel_id = _configured_channel_id(conf, legacy_column)
        if not legacy_channel_id:
            continue
        channel = guild.get_channel(legacy_channel_id)
        if not isinstance(channel, discord.TextChannel):
            continue

        stats["seen"] += 1
        if await _repair_bot_permissions(guild, legacy_channel_id):
            stats["permissions"] += 1

        try:
            setting = await log_service.get_log_setting(bot, guild.id, log_type)
        except Exception:
            logger.exception("Lecture du log %s impossible sur guild=%s.", log_type, guild.id)
            continue

        current_channel_id = setting.get("channel_id")
        current_channel = guild.get_channel(int(current_channel_id)) if current_channel_id else None
        needs_route_repair = not isinstance(current_channel, discord.TextChannel)

        if force_enable or needs_route_repair:
            await log_service.set_log_channel(bot, guild.id, log_type, legacy_channel_id)
            setting["channel_id"] = legacy_channel_id
            stats["routed"] += 1

        # Une migration sans salon valide n'est pas une desactivation volontaire. On
        # l'active. En revanche, au demarrage normal, enabled=False + salon valide est
        # respecte comme choix administrateur. create-logs force volontairement l'activation.
        if force_enable or needs_route_repair:
            try:
                await log_service.set_log_enabled(bot, guild.id, log_type, True)
                stats["enabled"] += 1
            except ValueError:
                logger.warning("Activation impossible pour %s sur guild=%s : aucun salon.", log_type, guild.id)

    return stats


def _install_log_producer_fix() -> None:
    """Un seul processus AutoShardedBot produit les evenements : aucun kill-switch requis."""
    current = log_service.is_primary_process
    if getattr(current, "_sentrix_runtime_fix_v1", False):
        return

    def always_produce_logs() -> bool:
        return True

    always_produce_logs._sentrix_runtime_fix_v1 = True
    always_produce_logs._sentrix_original = current
    log_service.is_primary_process = always_produce_logs


def _patch_create_logs() -> None:
    current = Configuration.create_log_channels
    if getattr(current, "_sentrix_runtime_fix_v1", False):
        return

    async def create_log_channels_repaired(
        self: Configuration,
        guild: discord.Guild,
        author: discord.Member,
    ):
        created = await current(self, guild, author)
        stats = await repair_guild_logs(self.bot, guild, force_enable=True)
        logger.info(
            "create-logs synchronise guild=%s created=%s routed=%s enabled=%s permissions=%s",
            guild.id,
            len(created),
            stats["routed"],
            stats["enabled"],
            stats["permissions"],
        )
        return created

    create_log_channels_repaired._sentrix_runtime_fix_v1 = True
    create_log_channels_repaired._sentrix_original = current
    Configuration.create_log_channels = create_log_channels_repaired


def _patch_server_builder() -> None:
    current = ServerBuilder.build_server
    if getattr(current, "_sentrix_runtime_fix_v1", False):
        return

    async def build_server_repaired(self: ServerBuilder, guild, template_key, author):
        result = await current(self, guild, template_key, author)
        try:
            await repair_guild_logs(self.bot, guild, force_enable=True)
        except Exception:
            logger.exception("Reparation des logs apres create-server impossible sur guild=%s.", guild.id)
        return result

    build_server_repaired._sentrix_runtime_fix_v1 = True
    build_server_repaired._sentrix_original = current
    ServerBuilder.build_server = build_server_repaired


class RuntimeFixV1(commands.Cog, name="RuntimeFixV1"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._repaired_once = False
        self._repair_task: asyncio.Task | None = None

    @commands.Cog.listener()
    async def on_ready(self):
        if self._repaired_once:
            return
        self._repaired_once = True

        async def runner():
            total_seen = total_routed = total_enabled = total_permissions = 0
            for guild in list(self.bot.guilds):
                try:
                    stats = await repair_guild_logs(self.bot, guild, force_enable=False)
                    total_seen += stats["seen"]
                    total_routed += stats["routed"]
                    total_enabled += stats["enabled"]
                    total_permissions += stats["permissions"]
                except Exception:
                    logger.exception("Reparation runtime des logs impossible sur guild=%s.", guild.id)
            logger.info(
                "Reparation runtime terminee : salons=%s routes=%s actives=%s permissions_ok=%s.",
                total_seen,
                total_routed,
                total_enabled,
                total_permissions,
            )

        self._repair_task = asyncio.create_task(runner())


async def setup(bot: commands.Bot) -> None:
    # Cette installation doit etre la derniere couche visuelle du runtime.
    final_interaction_policy.install(bot)
    _install_log_producer_fix()
    _patch_create_logs()
    _patch_server_builder()

    existing = bot.get_cog("RuntimeFixV1")
    if existing is not None:
        await bot.remove_cog("RuntimeFixV1")
    await bot.add_cog(RuntimeFixV1(bot))

    bot._sentrix_runtime_fix_v1 = True
    logger.info(
        "RuntimeFixV1 actif : transport embed final installe et routage logs auto-repare."
    )
