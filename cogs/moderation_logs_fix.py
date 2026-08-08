"""Fiabilise les logs de modération sans modifier le moteur de sanctions.

Deux problèmes sont corrigés :
- si le salon enregistré dans log_settings a été supprimé/déplacé mais qu'un salon de
  modération valide existe encore, le routage se répare automatiquement ;
- les événements Discord ban/unban/timeout ne créent plus un second log générique juste
  après la fiche détaillée produite par une commande SentriX.

Les actions effectuées directement depuis Discord ou par un autre bot restent journalisées.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata

import discord
from discord.ext import commands

from utils import log_service

logger = logging.getLogger("bot.moderation-logs-fix")

_INSTALLED_ROUTING = False
_INSTALLED_DEDUPE = False

_GENERIC_ACTIONS = {
    "Membre banni": ("ban", "tempban"),
    "Membre débanni": ("unban",),
}

_MODERATION_CHANNEL_NAMES = {
    "logs-moderation",
    "log-moderation",
    "moderation-logs",
    "logs-sanctions",
}


def _plain_name(value: str | None) -> str:
    text = (value or "").strip()
    if "・" in text:
        text = text.split("・", 1)[1]
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.casefold().replace("_", "-").replace(" ", "-")


def _valid_log_channel(guild: discord.Guild, channel_id: int | None) -> discord.TextChannel | None:
    if not channel_id:
        return None
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return None
    ok, _reason = log_service.validate_channel(guild, channel.id)
    return channel if ok else None


async def _repair_moderation_target(bot: commands.Bot, guild: discord.Guild) -> int | None:
    """Trouve un salon valide sans réactiver un log volontairement désactivé."""
    setting = await log_service.get_log_setting(bot, guild.id, "moderation")
    if not setting["enabled"]:
        return None

    current = _valid_log_channel(guild, setting["channel_id"])
    if current is not None:
        return current.id

    candidates: list[int] = []
    try:
        conf = await bot.db.get_guild_config(guild.id)
    except Exception:
        conf = None

    if conf:
        for key in ("log_moderation", "log_channel"):
            try:
                value = conf[key]
            except (KeyError, IndexError):
                value = None
            if value and int(value) not in candidates:
                candidates.append(int(value))

    for channel_id in candidates:
        channel = _valid_log_channel(guild, channel_id)
        if channel is None:
            continue
        await log_service.set_log_channel(bot, guild.id, "moderation", channel.id)
        await bot.db.set_guild_config(guild.id, "log_moderation", channel.id)
        logger.info(
            "Logs modération réparés sur %s (%s) : salon existant %s réutilisé.",
            guild.name,
            guild.id,
            channel.id,
        )
        return channel.id

    # Dernier repli : retrouver le salon par son nom. Cela couvre notamment un salon
    # supprimé/recréé avec un nouvel ID après +create-server.
    for channel in guild.text_channels:
        if _plain_name(channel.name) not in _MODERATION_CHANNEL_NAMES:
            continue
        if _valid_log_channel(guild, channel.id) is None:
            continue
        await log_service.set_log_channel(bot, guild.id, "moderation", channel.id)
        await bot.db.set_guild_config(guild.id, "log_moderation", channel.id)
        await bot.db.set_guild_config(guild.id, "log_channel", channel.id)
        logger.info(
            "Logs modération réparés sur %s (%s) : #%s détecté automatiquement.",
            guild.name,
            guild.id,
            channel.name,
        )
        return channel.id

    return None


def _target_id(embed: discord.Embed) -> int | None:
    footer = getattr(getattr(embed, "footer", None), "text", None) or ""
    match = re.search(r"(\d{10,24})", footer)
    return int(match.group(1)) if match else None


def _timeout_action(embed: discord.Embed) -> tuple[str, ...]:
    for field in embed.fields:
        if field.name == "Nouvel état":
            return ("unmute",) if "retir" in str(field.value).casefold() else ("mute",)
    return ("mute", "unmute")


async def _has_recent_detailed_sanction(
    bot: commands.Bot,
    guild_id: int,
    user_id: int,
    actions: tuple[str, ...],
) -> bool:
    placeholders = ",".join("?" for _ in actions)
    # Le listener Discord peut partir quelques millisecondes AVANT que Moderation.log_sanction
    # n'écrive son dossier. Une courte attente laisse la fiche détaillée devenir visible en DB.
    await asyncio.sleep(1.15)
    row = await bot.db.fetchone(
        f"""
        SELECT 1
        FROM sanctions
        WHERE guild_id = ?
          AND user_id = ?
          AND action IN ({placeholders})
          AND created_at >= ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (guild_id, user_id, *actions, int(time.time()) - 8),
    )
    return row is not None


def _install_routing_repair() -> None:
    global _INSTALLED_ROUTING
    if _INSTALLED_ROUTING:
        return

    original_send_log = log_service.send_log
    if getattr(original_send_log, "_sentrix_moderation_log_repair", False):
        _INSTALLED_ROUTING = True
        return

    async def send_log_repaired(
        bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        file: discord.File | None = None,
    ) -> bool:
        if log_type == "moderation":
            try:
                setting = await log_service.get_log_setting(bot, guild.id, "moderation")
                if setting["enabled"]:
                    ok, _reason = log_service.validate_channel(
                        guild,
                        setting["channel_id"],
                        needs_file=file is not None,
                    )
                    if not ok:
                        await _repair_moderation_target(bot, guild)
            except Exception:
                # Le log ne doit jamais faire échouer la sanction principale.
                logger.exception(
                    "Réparation du salon de logs modération impossible sur %s (%s).",
                    guild.name,
                    guild.id,
                )

        return await original_send_log(bot, guild, log_type, embed, file=file)

    send_log_repaired._sentrix_moderation_log_repair = True
    log_service.send_log = send_log_repaired
    _INSTALLED_ROUTING = True
    logger.info("Auto-réparation du routage des logs de modération activée.")


def _install_generic_dedupe(bot: commands.Bot) -> None:
    global _INSTALLED_DEDUPE
    if _INSTALLED_DEDUPE:
        return

    logs_cog = bot.get_cog("Logs")
    if logs_cog is None:
        return

    cls = type(logs_cog)
    original_send = cls._send
    if getattr(original_send, "_sentrix_moderation_log_dedupe", False):
        _INSTALLED_DEDUPE = True
        return

    async def send_without_duplicate(self, guild: discord.Guild, config_key: str, embed: discord.Embed):
        if config_key == "log_moderation":
            title = str(embed.title or "")
            actions = _GENERIC_ACTIONS.get(title)
            if title == "Timeout modifié":
                actions = _timeout_action(embed)

            target_id = _target_id(embed)
            if actions and target_id:
                try:
                    if await _has_recent_detailed_sanction(
                        self.bot,
                        guild.id,
                        target_id,
                        actions,
                    ):
                        logger.debug(
                            "Log générique %s ignoré : fiche de sanction SentriX déjà créée "
                            "(guild=%s, user=%s).",
                            title,
                            guild.id,
                            target_id,
                        )
                        return
                except Exception:
                    logger.exception(
                        "Déduplication du log modération impossible (guild=%s, user=%s).",
                        guild.id,
                        target_id,
                    )

        return await original_send(self, guild, config_key, embed)

    send_without_duplicate._sentrix_moderation_log_dedupe = True
    cls._send = send_without_duplicate
    _INSTALLED_DEDUPE = True
    logger.info("Déduplication ban/unban/timeout des logs de modération activée.")


def install(bot: commands.Bot) -> None:
    """Peut être appelé après chaque extension ; les patches sont idempotents."""
    _install_routing_repair()
    _install_generic_dedupe(bot)
