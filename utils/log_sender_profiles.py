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


def default_profile(bot, category: str) -> dict:
    """Le mini-profil des logs est actif d'office, sans configuration.

    Le nom ne remplace pas la fiche de l'application : seul le petit profil du
    message webhook est modifié. Aucun changement des autres réglages de logs.
    """
    from utils.log_categories import CATEGORIES

    labels = {
        "members": "Arrivées & Départs",
        "tickets": "Tickets",
        "moderation": "Modération",
        "messages": "Messages",
        "voice": "Activité vocale",
        "automod": "Protection AutoMod",
        "raid": "Protection Anti-Raid",
        "spam": "Protection Anti-Spam",
    }
    name = labels.get(category, CATEGORIES.get(category, "Journaux"))
    user = getattr(bot, "user", None)
    avatar = getattr(user, "display_avatar", None)
    url = str(getattr(avatar, "url", "") or "")
    return {"enabled": True, "display_name": name, "avatar_url": url}


async def get_profile(bot, guild_id: int, category: str) -> dict:
    # Aucune option supplémentaire à régler pour les logs : le mini-profil
    # est désormais automatique. L'éditeur /embed gère ses propres variantes.
    return default_profile(bot, category)


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
    if getattr(view, "is_dispatchable", lambda: False)():
        return False
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
                                                    reason="Mini-profils automatiques des logs SentriX")
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
    webhook = await _webhook(channel)
    if webhook is None:
        logger.debug("Mini-profil non disponible : permission webhook absente channel=%s", channel.id)
        return None

    # Un webhook créé par l'application possède son application_id.
    # Discord autorise les composants interactifs UNIQUEMENT sur ces
    # webhooks ; les autres n'acceptent que des composants non interactifs.
    # Ne jamais retirer les boutons pour forcer un mini-profil.
    has_actions = not is_noninteractive(view)
    app_id = getattr(getattr(channel.guild, "me", None), "id", None)
    owner_id = getattr(webhook, "application_id", None)
    if has_actions and not (app_id and owner_id and int(app_id) == int(owner_id)):
        logger.info(
            "Log conservé sous SentriX (actions requises, webhook non-app-owned) "
            "channel=%s application_owned=%s",
            channel.id, bool(owner_id),
        )
        return None
    try:
        result = await webhook.send(
            view=view,
            files=files,
            wait=True,
            username=profile["display_name"],
            avatar_url=profile["avatar_url"] or None,
            allowed_mentions=allowed_mentions,
        )
        logger.info(
            "Mini-profil envoyé via webhook channel=%s message=%s actions=%s",
            channel.id, getattr(result, "id", None), has_actions,
        )
        return result
    except (discord.Forbidden, discord.HTTPException, ValueError, TypeError) as exc:
        logger.warning(
            "Webhook mini-profil refusé channel=%s actions=%s erreur=%s; envoi par bot",
            channel.id, has_actions, type(exc).__name__,
        )
        _webhooks.pop((int(channel.guild.id), int(channel.id)), None)
        return None


async def send_embed_with_identity(
    channel: discord.TextChannel, *, sender_name: str,
    sender_avatar_url: str, content: str | None, embed: discord.Embed | None,
    view: discord.ui.View | None = None,
    allowed_mentions: discord.AllowedMentions | None = None,
):
    """Envoie un /embed avec un petit profil personnalisable, jamais un faux bot.

    Seuls des boutons URL sont autorisés. Si le webhook n'est pas disponible,
    l'appelant affiche l'erreur, au lieu de publier sous une autre identité.
    """
    name, avatar = validate_profile(sender_name, sender_avatar_url)
    if view is not None and not is_noninteractive(view):
        raise ValueError("L'envoi personnalisé accepte uniquement les boutons de lien.")
    hook = await _webhook(channel)
    if hook is None:
        raise ValueError(
            "Pour personnaliser le mini-profil, accordez à SentriX la permission "
            "Gérer les webhooks dans ce salon."
        )
    return await hook.send(
        content=content, embed=embed, view=view,
        username=name, avatar_url=avatar or None,
        allowed_mentions=allowed_mentions or discord.AllowedMentions.none(),
        wait=True,
    )
