"""SentriX V3.6 — pack officiel d'emojis animés pour toute l'interface.

Cette couche ne crée aucune commande et ne modifie aucune permission métier.
Elle synchronise neuf GIFs légers sur le serveur officiel SentriX, mémorise leurs IDs
Discord, puis remplace les anciens pictogrammes de l'interface par ce pack dans les
embeds, boutons et menus qui passent par le moteur premium global.

Important : aucun emoji existant du serveur n'est supprimé. Si SentriX ne possède pas
la permission de gérer les expressions, le bot continue de démarrer normalement et
l'interface reste simplement sans pictogramme personnalisé jusqu'à correction.
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands

from utils import premium_style

logger = logging.getLogger("bot.sentrix-animated-emojis")

OFFICIAL_INVITE = "https://discord.gg/5P5Bqjqu5t"
ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "sentrix_emojis"

PACK: dict[str, tuple[str, str]] = {
    "loading": ("sxv36_loading", "sentrix_loading.gif"),
    "ok": ("sxv36_ok", "sentrix_ok.gif"),
    "error": ("sxv36_error", "sentrix_error.gif"),
    "no": ("sxv36_no", "sentrix_no.gif"),
    "alert": ("sxv36_alert", "sentrix_alert.gif"),
    "ticket": ("sxv36_ticket", "sentrix_ticket.gif"),
    "staff": ("sxv36_staff", "sentrix_staff.gif"),
    "update": ("sxv36_update", "sentrix_update.gif"),
    "online": ("sxv36_online", "sentrix_online.gif"),
}

_REGISTRY: dict[str, discord.Emoji] = {}
_SYNC_LOCK = asyncio.Lock()
_INSTALLED = False

# Anciennes icônes système les plus utilisées par help/setup/tickets/modération.
# Elles sont remplacées, jamais empilées avec les nouvelles.
_TOKEN_TO_KEY: tuple[tuple[str, str], ...] = (
    ("✅", "ok"), ("☑️", "ok"), ("✔️", "ok"), ("✓", "ok"),
    ("❌", "error"), ("❎", "error"), ("✖️", "error"), ("✕", "error"),
    ("⛔", "no"), ("🚫", "no"), ("🛑", "no"),
    ("⚠️", "alert"), ("⚠", "alert"), ("🚨", "alert"), ("❗", "alert"), ("❕", "alert"),
    ("🎫", "ticket"), ("🎟️", "ticket"),
    ("🛡️", "staff"), ("🔨", "staff"), ("👑", "staff"), ("🧪", "staff"), ("🎭", "staff"),
    ("⚙️", "update"), ("🔄", "update"), ("🔃", "update"), ("♻️", "update"),
    ("📢", "update"), ("🚀", "update"), ("✨", "update"), ("📚", "update"),
    ("🟢", "online"), ("🟩", "online"), ("🌐", "online"), ("📊", "online"),
    ("📈", "online"), ("🤖", "online"), ("🎮", "online"), ("🏠", "online"),
    ("⏳", "loading"), ("⌛", "loading"), ("🔎", "loading"), ("⌕", "loading"),
    ("▶️", "update"), ("◀️", "update"),
    ("🐞", "error"), ("❓", "alert"), ("❔", "alert"), ("💡", "alert"),
    ("💎", "ok"), ("🎉", "ok"), ("🎁", "ok"), ("🏆", "ok"), ("🤝", "ok"),
    ("💬", "ticket"), ("📋", "staff"), ("🔥", "online"),
)

_LEADING_UI_RE = re.compile(
    r"^(?:\s|[\u2600-\u27BF\u2B00-\u2BFF\U0001F000-\U0001FAFF]|[\uFE0F\u200D]|[✦⌕✓✕▶◀])+",
    flags=re.UNICODE,
)
_CUSTOM_EMOJI_RE = re.compile(r"<a?:[A-Za-z0-9_~]+:\d+>")

_CATEGORY_KEYS = {
    "moderation": "staff",
    "security": "staff",
    "tickets": "ticket",
    "configuration": "update",
    "logs": "online",
    "events": "update",
    "invites": "ok",
    "premium": "ok",
    "brand": "online",
    "utility": "online",
    "profile": "online",
    "levels": "online",
    "leaderboard": "online",
    "economy": "online",
    "shop": "ok",
    "games": "online",
    "music": "online",
    "ai": "online",
}


def emoji(key: str) -> discord.Emoji | None:
    value = _REGISTRY.get(str(key))
    if value is None or getattr(value, "deleted", False):
        return None
    return value


def emoji_text(key: str) -> str:
    value = emoji(key)
    return str(value) if value is not None else ""


def _strip_leading_ui(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.startswith(("<a:", "<:")):
        return text
    return _LEADING_UI_RE.sub("", text).strip()


def _replace_known_tokens(value: Any) -> str:
    text = str(value or "")
    if not text:
        return text
    for token, key in _TOKEN_TO_KEY:
        if token not in text:
            continue
        text = text.replace(token, emoji_text(key))
    # Evite les doubles espaces laissés lorsqu'un emoji n'est pas encore synchronisé.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +\n", "\n", text)
    return text.strip()


def _semantic_key(
    text: Any = "",
    *,
    category: str | None = None,
    kind: str | None = None,
) -> str | None:
    if kind == "danger":
        return "error"
    if kind == "warning":
        return "alert"
    if kind == "success":
        return "ok"

    haystack = str(text or "").casefold()
    rules = (
        ("ticket", ("ticket", "support")),
        ("error", ("erreur", "error", "échoué", "echec", "failed", "bug", "supprimer", "delete", "fermer", "close", "annuler", "cancel")),
        ("no", ("refus", "denied", "interdit", "forbidden", "blacklist", "bloqué", "blocked")),
        ("alert", ("alerte", "alert", "attention", "warning", "avert", "report", "signal")),
        ("staff", ("staff", "modération", "moderation", "sécurité", "security", "admin", "ban", "mute", "warn", "rôle", "role")),
        ("update", ("setup", "config", "paramètre", "setting", "update", "mise à jour", "actualiser", "refresh", "save", "enregistrer")),
        ("loading", ("charg", "loading", "patiente", "wait", "recherch", "search", "génération", "generation")),
        ("online", ("online", "status", "statut", "ping", "latence", "latency", "live", "profil", "profile", "jeu", "game", "ia", " ai")),
        ("ok", ("succès", "success", "valider", "confirm", "créer", "create", "activer", "enable", "ajouter", "add", "envoyer", "send")),
    )
    for key, words in rules:
        if any(word in haystack for word in words):
            return key
    return _CATEGORY_KEYS.get(str(category or ""))


def _decorate_title(value: Any, *, key: str | None) -> str | None:
    if value is None:
        return None
    text = _replace_known_tokens(value)
    text = _CUSTOM_EMOJI_RE.sub("", text).strip()
    text = _strip_leading_ui(text)
    icon = emoji_text(key or "")
    return f"{icon} {text}".strip() if text else icon or "SentriX"


def _decorate_embed(
    embed: discord.Embed,
    *,
    command: Any = None,
    category: str | None = None,
    kind: str | None = None,
    log_type: str | None = None,
) -> discord.Embed:
    if log_type:
        return embed

    resolved_category = premium_style.infer_category(command=command, embed=embed, hint=category)
    if resolved_category == "logs":
        return embed
    resolved_kind = kind or premium_style.infer_kind(embed)
    key = _semantic_key(
        f"{getattr(embed, 'title', '')} {getattr(embed, 'description', '')}",
        category=resolved_category,
        kind=resolved_kind,
    )

    embed.title = _decorate_title(getattr(embed, "title", None), key=key)
    if embed.description is not None:
        embed.description = _replace_known_tokens(embed.description)[:4096] or None

    for index, field in enumerate(list(embed.fields)):
        field_key = _semantic_key(
            f"{field.name} {field.value}",
            category=resolved_category,
            kind=None,
        )
        name = _decorate_title(field.name, key=field_key)
        value = _replace_known_tokens(field.value)[:1024] or "—"
        embed.set_field_at(index, name=(name or "Information")[:256], value=value, inline=bool(field.inline))
    return embed


def _decorate_view(view: discord.ui.View | None) -> discord.ui.View | None:
    if view is None:
        return None
    for item in list(getattr(view, "children", ()) or ()):
        if isinstance(item, discord.ui.Button):
            label = _strip_leading_ui(_replace_known_tokens(item.label or ""))
            if item.label is not None:
                item.label = label[:80] or "Action"
            key = _semantic_key(f"{label} {item.custom_id or ''}")
            # V3.6 remplace l'ancien emoji au lieu de l'empiler.
            item.emoji = emoji(key) if key else None
            continue

        if isinstance(item, discord.ui.Select):
            for option in list(getattr(item, "options", ()) or ()):
                label = _strip_leading_ui(_replace_known_tokens(option.label or ""))
                option.label = label[:100] or "Option"
                key = _semantic_key(f"{label} {option.value} {option.description or ''}")
                option.emoji = emoji(key) if key else None
    return view


async def _read_setting(bot: commands.Bot, key: str) -> str | None:
    try:
        row = await bot.db.fetchone("SELECT value FROM bot_settings WHERE key = ?", (key,))
    except Exception:
        return None
    if not row:
        return None
    try:
        return str(row["value"])
    except Exception:
        try:
            return str(row[0])
        except Exception:
            return None


async def _resolve_official_guild(bot: commands.Bot) -> discord.Guild | None:
    runtime = getattr(bot, "_sentrix_official_server_runtime", None)
    if runtime is not None and callable(getattr(runtime, "official_guild_id", None)):
        try:
            guild_id = await runtime.official_guild_id()
            if guild_id:
                guild = bot.get_guild(int(guild_id))
                if guild is not None:
                    return guild
        except Exception:
            logger.debug("Résolution du serveur officiel via runtime impossible.", exc_info=True)

    for setting in ("sentrix_official_guild_id", "sentrix_release_announce_guild_id"):
        raw = await _read_setting(bot, setting)
        if not raw:
            continue
        try:
            guild = bot.get_guild(int(raw))
        except ValueError:
            guild = None
        if guild is not None:
            return guild

    # Fallback non destructif : le serveur officiel possède ces deux salons distinctifs.
    for guild in bot.guilds:
        names = {str(channel.name).casefold() for channel in guild.text_channels}
        if any("annonces-sentrix" in name for name in names) and any("règlement" in name or "reglement" in name for name in names):
            return guild

    try:
        invite = await bot.fetch_invite(OFFICIAL_INVITE, with_counts=False)
        guild_id = getattr(getattr(invite, "guild", None), "id", None)
        return bot.get_guild(int(guild_id)) if guild_id else None
    except Exception:
        return None


def _can_manage_expressions(guild: discord.Guild) -> bool:
    member = guild.me
    if member is None:
        return False
    perms = member.guild_permissions
    return bool(
        perms.administrator
        or getattr(perms, "manage_emojis_and_stickers", False)
        or getattr(perms, "manage_expressions", False)
    )


def _refresh_registry(emojis: list[discord.Emoji] | tuple[discord.Emoji, ...]) -> int:
    by_name = {emoji.name: emoji for emoji in emojis}
    _REGISTRY.clear()
    for key, (name, _filename) in PACK.items():
        value = by_name.get(name)
        if value is not None:
            _REGISTRY[key] = value
    return len(_REGISTRY)


async def sync_pack(bot: commands.Bot) -> int:
    """Crée/réutilise le pack animé sur le serveur officiel, sans supprimer d'emoji."""
    async with _SYNC_LOCK:
        guild = await _resolve_official_guild(bot)
        if guild is None:
            logger.warning("Pack emojis SentriX : serveur officiel introuvable ; synchronisation reportée.")
            return 0

        try:
            current = await guild.fetch_emojis()
        except (discord.Forbidden, discord.HTTPException):
            current = list(guild.emojis)

        count = _refresh_registry(list(current))
        if count == len(PACK):
            bot._sentrix_animated_emojis_ready = True
            bot._sentrix_emoji_registry = dict(_REGISTRY)
            return count

        if not _can_manage_expressions(guild):
            logger.warning(
                "Pack emojis SentriX : permission Gérer les expressions manquante sur %s (%s).",
                guild.name,
                guild.id,
            )
            bot._sentrix_emoji_registry = dict(_REGISTRY)
            return count

        existing_names = {value.name for value in current}
        for key, (name, filename) in PACK.items():
            if key in _REGISTRY or name in existing_names:
                continue
            path = ASSET_DIR / filename
            try:
                data = path.read_bytes()
            except OSError:
                logger.error("Pack emojis SentriX : asset introuvable %s.", path)
                continue
            try:
                created = await guild.create_custom_emoji(
                    name=name,
                    image=data,
                    reason="Pack UI animé SentriX V3.6",
                )
            except discord.Forbidden:
                logger.warning("Pack emojis SentriX : Discord refuse la création de %s (permission).", name)
                break
            except discord.HTTPException as exc:
                logger.warning("Pack emojis SentriX : création de %s impossible : %s", name, exc)
                continue
            _REGISTRY[key] = created
            existing_names.add(name)

        bot._sentrix_emoji_registry = dict(_REGISTRY)
        bot._sentrix_animated_emojis_ready = len(_REGISTRY) == len(PACK)
        logger.info(
            "Pack emojis SentriX synchronisé : %s/%s emoji(s) disponible(s) sur %s.",
            len(_REGISTRY),
            len(PACK),
            guild.name,
        )
        return len(_REGISTRY)


def _install_sync(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_emoji_sync_installed", False):
        return

    async def sync_on_ready() -> None:
        try:
            await sync_pack(bot)
        except Exception:
            logger.exception("Synchronisation du pack emojis SentriX impossible.")

    async def refresh_on_emoji_update(
        guild: discord.Guild,
        before: tuple[discord.Emoji, ...],
        after: tuple[discord.Emoji, ...],
    ) -> None:
        del before
        official = await _resolve_official_guild(bot)
        if official is None or guild.id != official.id:
            return
        _refresh_registry(after)
        bot._sentrix_emoji_registry = dict(_REGISTRY)
        bot._sentrix_animated_emojis_ready = len(_REGISTRY) == len(PACK)

    bot.add_listener(sync_on_ready, "on_ready")
    bot.add_listener(refresh_on_emoji_update, "on_guild_emojis_update")
    bot._sentrix_emoji_sync_installed = True


def _install_visual_pipeline() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    original_embed = premium_style.style_embed
    original_view = premium_style.style_view

    def style_embed_v36(embed: discord.Embed, *args, **kwargs):
        result = original_embed(embed, *args, **kwargs)
        if not isinstance(result, discord.Embed):
            return result
        return _decorate_embed(
            result,
            command=kwargs.get("command"),
            category=kwargs.get("category"),
            kind=kwargs.get("kind"),
            log_type=kwargs.get("log_type"),
        )

    def style_view_v36(view: discord.ui.View | None):
        return _decorate_view(original_view(view))

    premium_style.style_embed = style_embed_v36
    premium_style.style_view = style_view_v36
    _INSTALLED = True


def install(bot: commands.Bot) -> None:
    _install_visual_pipeline()
    _install_sync(bot)
    bot._sentrix_animated_emoji_pack_v36 = True
    logger.info("SentriX V3.6 : pack animé officiel branché sur embeds, boutons et menus.")


__all__ = ["PACK", "emoji", "emoji_text", "install", "sync_pack"]
