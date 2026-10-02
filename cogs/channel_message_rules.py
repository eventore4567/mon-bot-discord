"""Règles de contenu par salon pour SentriX.

Deux modes volontairement simples :
- blocked: les messages des membres sont interdits ;
- images_only: uniquement des pièces jointes image, sans texte.

Les bots/webhooks et le staff disposant de Gérer les messages/Gérer le serveur/Admin
ne sont jamais bloqués afin de ne pas casser les outils d'administration.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import discord
from discord.ext import commands

logger = logging.getLogger("bot.channel-message-rules")

MODES = frozenset({"blocked", "images_only"})
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sentrix_channel_message_rules (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('blocked','images_only')),
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_by INTEGER,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
)
"""


async def ensure_schema(bot) -> None:
    await bot.db.execute(SCHEMA)
    await bot.db.execute(
        "CREATE INDEX IF NOT EXISTS idx_sentrix_channel_message_rules_guild "
        "ON sentrix_channel_message_rules(guild_id, enabled, channel_id)"
    )


def _row_dict(row: Any) -> dict:
    try:
        return dict(row) if row else {}
    except Exception:
        return {}


def _attachment_is_image(attachment) -> bool:
    content_type = str(getattr(attachment, "content_type", "") or "").casefold()
    if content_type.startswith("image/"):
        return True
    filename = str(getattr(attachment, "filename", "") or "").casefold()
    return filename.endswith(IMAGE_EXTENSIONS)


def message_is_images_only(message) -> bool:
    """True seulement si le message contient >=1 image et aucun texte/autre fichier."""
    if str(getattr(message, "content", "") or "").strip():
        return False
    attachments = list(getattr(message, "attachments", ()) or ())
    if not attachments:
        return False
    return all(_attachment_is_image(item) for item in attachments)


def member_bypasses(member) -> bool:
    if getattr(member, "bot", False):
        return True
    perms = getattr(member, "guild_permissions", None)
    if perms is None:
        return False
    return bool(
        getattr(perms, "administrator", False)
        or getattr(perms, "manage_guild", False)
        or getattr(perms, "manage_messages", False)
    )


def invalidate_cache(bot, guild_id: int | None = None, channel_id: int | None = None) -> None:
    cache = getattr(bot, "_sentrix_channel_rule_cache", None)
    if not isinstance(cache, dict):
        return
    if guild_id is None:
        cache.clear()
        return
    for key in list(cache):
        if key[0] != int(guild_id):
            continue
        if channel_id is None or key[1] == int(channel_id):
            cache.pop(key, None)


async def list_rules(bot, guild: discord.Guild) -> list[dict]:
    await ensure_schema(bot)
    rows = await bot.db.fetchall(
        "SELECT guild_id,channel_id,mode,enabled,updated_by,updated_at "
        "FROM sentrix_channel_message_rules WHERE guild_id=? ORDER BY channel_id",
        (guild.id,),
    )
    items: list[dict] = []
    for row in rows:
        item = _row_dict(row)
        channel = guild.get_channel(int(item.get("channel_id") or 0))
        items.append({
            "channel_id": str(item.get("channel_id") or ""),
            "channel_name": getattr(channel, "name", None),
            "mode": str(item.get("mode") or "blocked"),
            "enabled": bool(item.get("enabled")),
            "updated_by": str(item.get("updated_by") or ""),
            "updated_at": int(item.get("updated_at") or 0),
        })
    return items


def _validate_channel(guild: discord.Guild, channel_id: int) -> discord.TextChannel:
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("Choisissez un salon textuel.")
    me = guild.me
    if me is not None:
        perms = channel.permissions_for(me)
        missing = []
        if not perms.view_channel:
            missing.append("Voir le salon")
        if not perms.manage_messages:
            missing.append("Gérer les messages")
        if missing:
            raise ValueError(
                f"SentriX ne peut pas appliquer la règle dans {channel.mention} : "
                f"permission(s) manquante(s) {', '.join(missing)}."
            )
    return channel


async def save_rule(
    bot,
    guild: discord.Guild,
    channel_id: int,
    mode: str,
    *,
    actor_id: int | None = None,
) -> dict:
    await ensure_schema(bot)
    mode = str(mode or "").casefold()
    if mode not in MODES:
        raise ValueError("Mode de salon invalide.")
    channel = _validate_channel(guild, int(channel_id))
    now = int(time.time())
    await bot.db.execute(
        "INSERT INTO sentrix_channel_message_rules "
        "(guild_id,channel_id,mode,enabled,updated_by,updated_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(guild_id,channel_id) DO UPDATE SET "
        "mode=excluded.mode,enabled=1,updated_by=excluded.updated_by,updated_at=excluded.updated_at",
        (guild.id, channel.id, mode, 1, actor_id, now),
    )
    invalidate_cache(bot, guild.id, channel.id)
    return {
        "channel_id": str(channel.id),
        "channel_name": channel.name,
        "mode": mode,
        "enabled": True,
    }


async def delete_rule(bot, guild_id: int, channel_id: int) -> None:
    await ensure_schema(bot)
    await bot.db.execute(
        "DELETE FROM sentrix_channel_message_rules WHERE guild_id=? AND channel_id=?",
        (int(guild_id), int(channel_id)),
    )
    invalidate_cache(bot, guild_id, channel_id)


async def toggle_rule(bot, guild_id: int, channel_id: int, enabled: bool, *, actor_id: int | None = None) -> None:
    await ensure_schema(bot)
    await bot.db.execute(
        "UPDATE sentrix_channel_message_rules SET enabled=?,updated_by=?,updated_at=? "
        "WHERE guild_id=? AND channel_id=?",
        (1 if enabled else 0, actor_id, int(time.time()), int(guild_id), int(channel_id)),
    )
    invalidate_cache(bot, guild_id, channel_id)


async def _rule_for(bot, guild_id: int, channel_id: int) -> dict | None:
    await ensure_schema(bot)
    cache = getattr(bot, "_sentrix_channel_rule_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        bot._sentrix_channel_rule_cache = cache
    key = (int(guild_id), int(channel_id))
    now = time.monotonic()
    hit = cache.get(key)
    if hit and now - hit[0] < 2.5:
        return hit[1]
    row = await bot.db.fetchone(
        "SELECT mode,enabled FROM sentrix_channel_message_rules "
        "WHERE guild_id=? AND channel_id=? LIMIT 1",
        key,
    )
    value = _row_dict(row) if row else None
    cache[key] = (now, value)
    return value


async def restricts_bot_text(bot, guild_id: int, channel_id: int) -> bool:
    """True si ce salon est configuré pour rester sans réponses textuelles SentriX.

    Utilisé notamment par SentriX AI pour ne pas polluer un salon media-only ou
    un salon où les messages sont interdits.
    """
    rule = await _rule_for(bot, int(guild_id), int(channel_id))
    if not rule or not bool(rule.get("enabled")):
        return False
    return str(rule.get("mode") or "") in MODES


async def _warn_after_delete(bot, message: discord.Message, mode: str) -> None:
    # Ne jamais polluer le salon protégé avec un message SentriX après avoir
    # supprimé celui du membre. L'information part uniquement en DM, avec un
    # cooldown large ; si les DMs sont fermés, la suppression reste silencieuse.
    cooldowns = getattr(bot, "_sentrix_channel_rule_warning_cooldowns", None)
    if not isinstance(cooldowns, dict):
        cooldowns = {}
        bot._sentrix_channel_rule_warning_cooldowns = cooldowns
    key = (message.guild.id, message.channel.id, message.author.id, mode)
    now = time.monotonic()
    if now - float(cooldowns.get(key, 0.0)) < 30.0:
        return
    cooldowns[key] = now
    text = (
        f"Dans #{message.channel.name}, seuls les messages contenant une image sans texte sont autorisés."
        if mode == "images_only"
        else f"Les messages des membres sont désactivés dans #{message.channel.name}."
    )
    try:
        await message.author.send(text)
    except (discord.Forbidden, discord.HTTPException):
        pass


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_channel_message_rules_installed", False):
        return
    bot._sentrix_channel_message_rules_installed = True
    bot._sentrix_channel_rule_cache = {}

    async def on_message(message: discord.Message) -> None:
        if message.guild is None or message.author is None:
            return
        if getattr(message, "webhook_id", None) is not None:
            return
        if not isinstance(message.author, discord.Member):
            return

        rule = await _rule_for(bot, message.guild.id, message.channel.id)
        if not rule or not bool(rule.get("enabled")):
            return
        mode = str(rule.get("mode") or "")
        if mode not in MODES:
            return

        # SentriX lui-même respecte la règle. Ainsi une réponse IA, un message
        # d'aide ou un vieux callback ne peut pas polluer un salon media-only.
        is_sentrix = bot.user is not None and int(message.author.id) == int(bot.user.id)
        if is_sentrix:
            if mode == "images_only" and message_is_images_only(message):
                return
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
            return

        # Les autres bots/webhooks et le staff restent hors du filtrage.
        if member_bypasses(message.author):
            return
        if mode == "images_only" and message_is_images_only(message):
            return
        local_deleters = getattr(bot, "_sentrix_local_message_deleters", None)
        if not isinstance(local_deleters, dict):
            local_deleters = {}
            bot._sentrix_local_message_deleters = local_deleters
        local_deleters[int(message.id)] = (time.monotonic(), int(bot.user.id) if bot.user else 0)
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            local_deleters.pop(int(message.id), None)
            return
        except discord.HTTPException:
            logger.debug(
                "Suppression règle de salon impossible guild=%s channel=%s",
                message.guild.id,
                message.channel.id,
                exc_info=True,
            )
            return
        await _warn_after_delete(bot, message, mode)

    bot.add_listener(on_message, "on_message")
    logger.info("Règles de salons SentriX installées.")


__all__ = [
    "MODES",
    "ensure_schema",
    "list_rules",
    "save_rule",
    "delete_rule",
    "toggle_rule",
    "message_is_images_only",
    "member_bypasses",
    "restricts_bot_text",
    "install",
]
