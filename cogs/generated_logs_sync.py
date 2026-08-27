"""Synchronise les salons LOGS existants avec le moteur ``log_settings``.

Le bot a utilisé plusieurs conventions de noms au fil des versions. Le constructeur
historique, ``/create-logs`` et ``+create-server`` n'ont pas toujours créé exactement les
mêmes noms (singulier/pluriel, accents, etc.). Après un redéploiement Railway avec une
SQLite vide, ces salons Discord restent présents mais la configuration locale peut être
perdue. Cette couche les redécouvre donc directement dans Discord et reconstruit les routes
sans recréer de salons ni produire de doublons.
"""
from __future__ import annotations

import asyncio
import logging
import re
import unicodedata

import discord
from discord.ext import commands

from utils import log_service

logger = logging.getLogger("bot.generated-logs-sync")

# Toutes les variantes réellement utilisées par SentriX. Les noms de configuration.py
# (logs-membre, logs-vocal, logs-moderation, logs-securite...) sont inclus en plus des noms
# historiques de +create-server. V6 ajoute logs-salons et logs-dossiers comme noms officiels.
LOG_CHANNEL_ALIASES: dict[str, tuple[str, ...]] = {
    "messages": ("logs-messages", "logs-message"),
    "members": ("logs-membre", "logs-membres", "logs-member", "logs-members"),
    "voice": ("logs-vocal", "logs-vocaux", "logs-voice"),
    "roles": ("logs-roles", "logs-rôles", "logs-role", "logs-rôle"),
    "server": ("logs-salons", "logs-serveur", "logs-server"),
    "files": ("logs-dossiers", "logs-fichiers", "logs-files"),
    "moderation": ("logs-moderation", "logs-modération", "logs-modo"),
    "tickets": ("logs-tickets", "logs-ticket"),
    "automod": ("logs-securite", "logs-sécurité", "logs-automod", "logs-security"),
}


def _plain(value: str) -> str:
    """Normalise accents, séparateurs et préfixes visuels sans toucher au sens."""
    value = (value or "").strip()
    if "・" in value:
        value = value.split("・", 1)[1]
    # Les catégories/salons ont parfois un emoji ou un tiret long au début.
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold().replace("_", " ")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value


_NORMALIZED_ALIASES = {
    log_type: frozenset(_plain(name) for name in aliases)
    for log_type, aliases in LOG_CHANNEL_ALIASES.items()
}


def _looks_like_log_category(channel: discord.TextChannel) -> bool:
    category = getattr(channel, "category", None)
    if category is None:
        return False
    name = _plain(getattr(category, "name", ""))
    return "logs" in name or ("sentrix" in name and "log" in name)


def _find_log_channel(guild: discord.Guild, log_type: str) -> discord.TextChannel | None:
    wanted = _NORMALIZED_ALIASES.get(log_type, frozenset())
    if not wanted:
        return None

    # Priorité aux salons placés dans une vraie catégorie de logs SentriX.
    for channel in guild.text_channels:
        if _plain(channel.name) in wanted and _looks_like_log_category(channel):
            return channel
    for channel in guild.text_channels:
        if _plain(channel.name) in wanted:
            return channel
    return None


async def sync_generated_logs(bot: commands.Bot, guild: discord.Guild) -> int:
    """Redécouvre, route et active les salons logs-* réellement présents."""
    found: dict[str, discord.TextChannel] = {}
    for log_type in LOG_CHANNEL_ALIASES:
        channel = _find_log_channel(guild, log_type)
        if channel is not None:
            found[log_type] = channel

    # Deux noms exacts SentriX suffisent : l'ancienne condition >=3 empêchait précisément
    # la récupération quand seuls logs-messages + logs-serveur étaient reconnus à cause des
    # différences singulier/pluriel/accents.
    if len(found) < 2:
        logger.info(
            "Auto-récupération logs ignorée guild=%s : seulement %s salon(s) SentriX reconnu(s).",
            guild.id,
            len(found),
        )
        return 0

    # Si la base a été recréée, garantir d'abord la ligne guild_config.
    try:
        await bot.db.ensure_guild(guild.id)
    except Exception:
        logger.exception("Impossible de garantir guild_config avant resynchronisation guild=%s.", guild.id)

    synced = 0
    for log_type, channel in found.items():
        meta = log_service.LOG_TYPES.get(log_type, {})
        legacy_column = meta.get("legacy_column")
        try:
            if legacy_column:
                await bot.db.set_guild_config(guild.id, legacy_column, channel.id)
            await log_service.set_log_channel(bot, guild.id, log_type, channel.id)
            await log_service.set_log_enabled(bot, guild.id, log_type, True)
            synced += 1
        except Exception:
            logger.exception(
                "Resynchronisation impossible guild=%s type=%s channel=%s.",
                guild.id,
                log_type,
                channel.id,
            )

    # Compatibilité avec les modules historiques utilisant log_channel comme fallback.
    moderation = found.get("moderation")
    if moderation is not None:
        try:
            await bot.db.set_guild_config(guild.id, "log_channel", moderation.id)
        except Exception:
            logger.exception("Impossible de restaurer log_channel guild=%s.", guild.id)

    logger.warning(
        "Logs SentriX auto-récupérés guild=%s : %s/%s route(s) actives — %s.",
        guild.id,
        synced,
        len(found),
        ", ".join(f"{kind}=#{channel.name}" for kind, channel in found.items()),
    )
    return synced


async def _bootstrap(bot: commands.Bot) -> None:
    try:
        await bot.wait_until_ready()
    except RuntimeError:
        # Les audits chargent le bot hors connexion Discord : aucun bootstrap distant à faire.
        return
    await asyncio.sleep(4)
    for guild in list(bot.guilds):
        try:
            await sync_generated_logs(bot, guild)
        except Exception:
            logger.exception("Synchronisation des logs impossible sur %s (%s).", guild.name, guild.id)


def install(bot: commands.Bot) -> None:
    """Installe le hook une seule fois et le bootstrap une fois par instance de bot."""
    from . import server_builder

    original = server_builder.ServerBuilder._configure_bot_channels
    if not getattr(original, "_sentrix_log_settings_sync", False):
        async def configure_with_log_sync(self, guild, role_map, category_map, channel_map, staff_role_name):
            result = await original(self, guild, role_map, category_map, channel_map, staff_role_name)
            await sync_generated_logs(self.bot, guild)
            return result

        configure_with_log_sync._sentrix_log_settings_sync = True
        server_builder.ServerBuilder._configure_bot_channels = configure_with_log_sync

    if getattr(bot, "_sentrix_generated_logs_sync_installed", False):
        return
    bot._sentrix_generated_logs_sync_installed = True
    asyncio.create_task(_bootstrap(bot), name="sentrix-generated-logs-sync")
    logger.info("Synchronisation automatique de toutes les variantes de salons LOGS SentriX activée.")
