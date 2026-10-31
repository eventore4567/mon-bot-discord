"""Profils d'expéditeur des logs : noms/avatars par catégorie et par serveur.

Un webhook peut personnaliser le mini-profil d'un log non interactif. Les
composants avec boutons/callbacks restent envoyés par SentriX (message bot),
pour ne jamais désactiver les actions de modération et les tickets.
Les tokens webhook ne sont jamais sauvegardés en base.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from urllib.parse import urlsplit

import discord

logger = logging.getLogger("bot.log-sender-profiles")

SCHEMA = """CREATE TABLE IF NOT EXISTS log_sender_profiles (
    guild_id BIGINT NOT NULL,
    category TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    display_name TEXT NOT NULL DEFAULT '',
    avatar_url TEXT NOT NULL DEFAULT '',
    updated_at BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY(guild_id, category)
)"""
# Shared per-process webhook objects. No token is stored in the database.
_webhooks: dict[tuple[int, int], discord.Webhook] = {}
_locks: dict[tuple[int, int], asyncio.Lock] = {}
_schema_ready: set[int] = set()
_profile_cache: dict[tuple[int, str], tuple[float, dict]] = {}


async def ensure_schema(bot) -> None:
    # One DDL call per bot process, not one per log event.
    key = id(bot)
    if key not in _schema_ready:
        await bot.db.execute(SCHEMA)
        _schema_ready.add(key)


def validate_profile(display_name: str, avatar_url: str) -> tuple[str, str]:
    name = " ".join(str(display_name or "").split())
    avatar = str(avatar_url or "").strip()
    if not 1 <= len(name) <= 70:
        raise ValueError("Le nom doit contenir entre 1 et 70 caractères.")
    if any(ord(char) < 32 for char in name) or "@everyone" in name.casefold():
        raise ValueError("Nom de profil invalide.")
    if avatar:
        if len(avatar) > 450:
            raise ValueError("Adresse de l'avatar trop longue.")
        parsed = urlsplit(avatar)
        hostname = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or not hostname or parsed.username or parsed.password
                or parsed.fragment or hostname in {"localhost"} or hostname.endswith(".local")):
            raise ValueError("L'avatar doit être une adresse HTTPS publique.")
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise ValueError("Utilisez un domaine HTTPS public plutôt qu'une adresse IP.")
    return name, avatar


async def get_profile(bot, guild_id: int, category: str) -> dict:
    await ensure_schema(bot)
    key = (int(guild_id), str(category))
    cached = _profile_cache.get(key)
    if cached is not None and time.monotonic() - cached[0] < 30:
        return dict(cached[1])
    row = await bot.db.fetchone(
        "SELECT enabled, display_name, avatar_url FROM log_sender_profiles "
        "WHERE guild_id=? AND category=?", (int(guild_id), str(category)),
    )
    profile = {
        "enabled": bool(row["enabled"]) if row else False,
        "display_name": str(row["display_name"] or "") if row else "",
        "avatar_url": str(row["avatar_url"] or "") if row else "",
    }
    _profile_cache[key] = (time.monotonic(), profile)
    return profile


async def set_profile(bot, guild_id: int, category: str, *,
                      enabled: bool, display_name: str, avatar_url: str) -> dict:
    from utils.log_categories import CATEGORIES

    if category not in CATEGORIES:
        raise ValueError("Catégorie de logs inconnue.")
    if enabled:
        name, avatar = validate_profile(display_name, avatar_url)
    else:
        name = " ".join(str(display_name or "").split())[:70]
        avatar = str(avatar_url or "").strip()[:450]
        if name and avatar:
            name, avatar = validate_profile(name, avatar)
    await ensure_schema(bot)
    await bot.db.execute(
        "INSERT INTO log_sender_profiles "
        "(guild_id,category,enabled,display_name,avatar_url,updated_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(guild_id,category) DO UPDATE SET "
        "enabled=excluded.enabled,display_name=excluded.display_name,"
        "avatar_url=excluded.avatar_url,updated_at=excluded.updated_at",
        (int(guild_id), category, int(enabled), name, avatar, int(time.time())),
    )
    profile = {"enabled": bool(enabled), "display_name": name, "avatar_url": avatar}
    _profile_cache.pop((int(guild_id), str(category)), None)
    return profile


def is_noninteractive(view: discord.ui.View) -> bool:
    """Safe for incoming webhooks: no custom-ID actions, dropdowns or callbacks."""
    queue = list(getattr(view, "children", ()))
    while queue:
        item = queue.pop()
        if isinstance(item, discord.ui.Button):
            if item.style not in (discord.ButtonStyle.link,):
                return False
        if isinstance(item, discord.ui.Select):
            return False
        queue.extend(getattr(item, "children", ()))
    return True


async def _webhook(channel: discord.TextChannel) -> discord.Webhook | None:
    guild = channel.guild
    member = guild.me
    if not member or not channel.permissions_for(member).manage_webhooks:
        return None
    key = (int(guild.id), int(channel.id))
    cached = _webhooks.get(key)
    if cached is not None:
        return cached
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        cached = _webhooks.get(key)
        if cached is not None:
            return cached
        try:
            existing = await channel.webhooks()
            hook = next((item for item in existing
                         if item.name == "SentriX · Mini-profils"
                         and item.token and item.user and item.user.id == member.id), None)
            if hook is None:
                hook = await channel.create_webhook(name="SentriX · Mini-profils",
                                                    reason="Mini-profils de logs configurés par un administrateur")
            _webhooks[key] = hook
            return hook
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Impossible de créer le mini-profil webhook channel=%s", channel.id)
            return None


async def send_with_profile(channel, view: discord.ui.View, files: list[discord.File],
                            profile: dict, *, allowed_mentions: discord.AllowedMentions):
    """Returns the message, or None to let the bot send the original V2 card."""
    if not profile.get("enabled") or not isinstance(channel, discord.TextChannel):
        return None
    if not is_noninteractive(view):
        return None
    webhook = await _webhook(channel)
    if webhook is None:
        return None
    try:
        return await webhook.send(
            view=view,
            files=files,
            wait=True,
            username=profile["display_name"],
            avatar_url=profile["avatar_url"] or None,
            allowed_mentions=allowed_mentions,
        )
    except (discord.Forbidden, discord.HTTPException, ValueError, TypeError):
        logger.warning("Webhook profil indisponible channel=%s, envoi par bot", channel.id)
        _webhooks.pop((int(channel.guild.id), int(channel.id)), None)
        return None
