"""SentriX V3.9 — pack animé réservé aux états, navigation simple et lisible.

Les dix GIFs 64x64 restent disponibles et synchronisés sur le serveur officiel. Le design
V3.9 évite cependant d'utiliser un emoji animé devant chaque champ ou catégorie :
les animations servent aux vrais états (chargement, succès, erreur, alerte, mise à jour),
tandis que la navigation utilise des pictogrammes Unicode simples et immédiatement lisibles.

Aucune commande, permission métier ou logique de modération n'est modifiée.
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
    "loading": ("sxv37_loading", "sentrix_loading.gif"),
    "ok": ("sxv37_ok", "sentrix_ok.gif"),
    "error": ("sxv37_error", "sentrix_error.gif"),
    "no": ("sxv37_no", "sentrix_no.gif"),
    "alert": ("sxv37_alert", "sentrix_alert.gif"),
    "ticket": ("sxv37_ticket", "sentrix_ticket.gif"),
    "staff": ("sxv37_staff", "sentrix_staff.gif"),
    "update": ("sxv37_update", "sentrix_update.gif"),
    "online": ("sxv37_online", "sentrix_online.gif"),
    "premium": ("sxv37_premium", "sentrix_premium.gif"),
}
LEGACY_PACK_PREFIXES = ("sxv36_",)

_REGISTRY: dict[str, discord.Emoji] = {}
_SYNC_LOCK = asyncio.Lock()
_INSTALLED = False

_CUSTOM_EMOJI_RE = re.compile(r"<a?:[A-Za-z0-9_~]+:\d+>")
_PACK_TOKEN_RE = re.compile(r"<a?:sxv(?:36|37)_[A-Za-z0-9_~]+:\d+>\s*", re.I)
_BROKEN_PACK_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:<?a?:?|:)?sxv(?:36|37)_[A-Za-z0-9_~]+:\d+>",
    re.I,
)
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")

CATEGORY_ICONS: dict[str, str] = {
    "configuration": "⚙️", "security": "🛡️", "moderation": "🔨", "tickets": "🎫",
    "ai": "🤖", "utility": "🧰", "profile": "👤", "levels": "📈",
    "leaderboard": "🏆", "economy": "💰", "shop": "🛒", "games": "🎮",
    "music": "🎵", "events": "📅", "invites": "🔗", "premium": "💎", "brand": "✨",
}

STATIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("🔎", ("rechercher", "recherche", "chercher", "search", "trouver n’importe quoi", "trouver n'importe quoi")),
    ("🚀", ("commencer", "démarrer", "demarrer", "getting started", "start")),
    ("🧩", ("systèmes principaux", "systemes principaux", "main systems", "modules")),
    ("📡", ("en direct", "live", "gateway", "racines slash")),
    ("ℹ️", ("information", "informations", "info")),
    ("⚙️", ("setup", "configuration", "configurer", "paramètres", "parametres", "settings", "logs")),
    ("🛡️", ("sécurité", "securite", "security", "protection", "automod")),
    ("🔨", ("modération", "moderation", "ban", "mute", "warn", "sanction")),
    ("🎫", ("ticket", "support")),
    ("🤖", (" ia", "intelligence artificielle", " ai", "utilitaires")),
    ("🌍", ("communauté", "communaute", "community", "progression")),
    ("👤", ("profil", "profile", "userinfo")),
    ("📈", ("niveau", "level", "xp", "classement")),
    ("🎮", ("jeu", "game", "mini-jeu")),
    ("🎵", ("musique", "music")),
    ("🛒", ("boutique", "shop", "inventaire", "inventory")),
)

BUTTON_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("⚙️", ("setup", "config", "log", "paramètre", "setting", "dashboard")),
    ("🛡️", ("sécurité", "securite", "security", "automod", "protection")),
    ("🔨", ("modération", "moderation", "ban", "mute", "warn")),
    ("🎫", ("ticket", "support")),
    ("🔎", ("rechercher", "search", "chercher")),
    ("❌", ("fermer", "close", "annuler", "cancel", "supprimer", "delete")),
    ("✅", ("valider", "confirm", "confirmer", "enregistrer", "save")),
    ("⬅️", ("retour", "back", "précédent", "precedent")),
    ("➡️", ("suivant", "next")),
)


def emoji(key: str) -> discord.Emoji | None:
    value = _REGISTRY.get(str(key))
    if value is None or getattr(value, "deleted", False):
        return None
    return value


def emoji_text(key: str) -> str:
    value = emoji(key)
    return str(value) if value is not None else ""


def _protect_custom_tokens(text: str) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        key = f"\x00SXEMOJI{len(protected)}\x00"
        protected[key] = match.group(0)
        return key

    return _CUSTOM_EMOJI_RE.sub(replace, text), protected


def _restore_custom_tokens(text: str, protected: dict[str, str]) -> str:
    for key, value in protected.items():
        text = text.replace(key, value)
    return text


def _clean_artifacts(value: Any) -> str:
    """Nettoie les anciens fragments sans jamais abîmer un vrai <a:nom:id>."""
    text = str(value or "")
    if not text:
        return ""
    text, protected = _protect_custom_tokens(text)
    text = _BROKEN_PACK_RE.sub("", text)
    text = re.sub(r"(?m)^\s*<a\s+(?=\S)", "", text, flags=re.I)
    text = re.sub(r"(?m)^\s*(?:a\s+){2,8}(?=\S)", "", text, flags=re.I)
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = re.sub(r" +\n", "\n", text)
    return _restore_custom_tokens(text.strip(), protected)


def _strip_existing_icon(value: Any) -> str:
    text = _clean_artifacts(value)
    text = _CUSTOM_EMOJI_RE.sub("", text).strip()
    text = re.sub(r"^(?:[\u2600-\u27BF\u2B00-\u2BFF\U0001F000-\U0001FAFF][\uFE0F\u200D]?\s*)+", "", text).strip()
    return text


def _static_icon(text: Any, *, category: str | None = None) -> str:
    """Navigation = pictogramme simple, jamais une animation répétée partout."""
    haystack = f" {str(text or '').casefold()} "
    for icon, words in STATIC_RULES:
        if any(word in haystack for word in words):
            return icon
    return CATEGORY_ICONS.get(str(category or ""), "ℹ️")


def _animated_state_key(text: Any, *, kind: str | None = None) -> str | None:
    if kind == "danger":
        return "error"
    if kind == "warning":
        return "alert"
    if kind == "success":
        return "ok"
    haystack = str(text or "").casefold()
    if any(word in haystack for word in ("chargement", "loading", "patiente", "génération", "generation")):
        return "loading"
    if any(word in haystack for word in ("mise à jour", "mise a jour", "update en cours", "actualisation en cours")):
        return "update"
    if any(word in haystack for word in ("bot en ligne", "online", "connecté", "connecte")):
        return "online"
    if any(word in haystack for word in ("refusé", "refuse", "interdit", "denied")):
        return "no"
    return None


def _decorate_label(value: Any, *, category: str | None = None, kind: str | None = None) -> str:
    text = _strip_existing_icon(value) or "Information"
    state_key = _animated_state_key(text, kind=kind)
    if state_key:
        animated = emoji_text(state_key)
        if animated:
            return f"{animated} {text}".strip()
    return f"{_static_icon(text, category=category)} {text}".strip()


def _clean_body(value: Any) -> str:
    return _PACK_TOKEN_RE.sub("", _clean_artifacts(value)).strip()


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
    if embed.title is not None:
        embed.title = _decorate_label(embed.title, category=resolved_category, kind=resolved_kind)[:256]
    if embed.description is not None:
        embed.description = _clean_body(embed.description)[:4096] or None
    for index, field in enumerate(list(embed.fields)):
        clean_name = _strip_existing_icon(field.name)
        clean_value = _clean_body(field.value)[:1024] or "—"
        icon = _static_icon(f"{clean_name} {clean_value}", category=resolved_category)
        embed.set_field_at(
            index,
            name=f"{icon} {clean_name or 'Information'}"[:256],
            value=clean_value,
            inline=bool(field.inline),
        )
    return embed


def _button_animated_key(text: str) -> str | None:
    """Animation uniquement pour une action d'état, pas pour naviguer entre catégories."""
    haystack = str(text or "").casefold()
    if any(word in haystack for word in ("actualiser", "refresh", "update")):
        return "update"
    if any(word in haystack for word in ("valider", "confirm", "confirmer", "enregistrer", "save")):
        return "ok"
    if any(word in haystack for word in ("fermer", "close", "annuler", "cancel")):
        return "no"
    return None


def _button_icon(text: str) -> str | discord.Emoji | None:
    key = _button_animated_key(text)
    if key:
        animated = emoji(key)
        if animated is not None:
            return animated
    haystack = text.casefold()
    for icon, words in BUTTON_RULES:
        if any(word in haystack for word in words):
            return icon
    return None


def _decorate_view(view: discord.ui.View | None) -> discord.ui.View | None:
    if view is None:
        return None
    for item in list(getattr(view, "children", ()) or ()):
        if isinstance(item, discord.ui.Button):
            label = _strip_existing_icon(item.label or "")
            if item.label is not None:
                item.label = (label or "Action")[:80]
            item.emoji = _button_icon(f"{label} {item.custom_id or ''}")
            continue
        if isinstance(item, discord.ui.Select):
            for option in list(getattr(item, "options", ()) or ()):
                label = _strip_existing_icon(option.label or "")
                option.label = (label or "Option")[:100]
                icon = _button_icon(f"{label} {option.value} {option.description or ''}")
                option.emoji = icon if icon is not None else _static_icon(f"{label} {option.description or ''}")
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
            logger.debug("Résolution serveur officiel via runtime impossible.", exc_info=True)
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


def _is_legacy_pack_emoji_name(name: str | None) -> bool:
    value = str(name or "")
    return any(value.startswith(prefix) for prefix in LEGACY_PACK_PREFIXES)


def _refresh_registry(emojis: list[discord.Emoji] | tuple[discord.Emoji, ...]) -> int:
    by_name = {emoji.name: emoji for emoji in emojis}
    _REGISTRY.clear()
    for key, (name, _filename) in PACK.items():
        value = by_name.get(name)
        if value is not None:
            _REGISTRY[key] = value
    return len(_REGISTRY)


async def _delete_legacy_pack(guild: discord.Guild, current: list[discord.Emoji]) -> list[discord.Emoji]:
    """Supprime uniquement les emojis SentriX V3.6, jamais ceux de l'utilisateur."""
    legacy = [value for value in current if _is_legacy_pack_emoji_name(value.name)]
    if not legacy:
        return current
    if not _can_manage_expressions(guild):
        logger.warning("Pack SentriX : anciens sxv36_* présents mais permission insuffisante.")
        return current
    deleted_ids: set[int] = set()
    for value in legacy:
        try:
            await value.delete(reason="SentriX V3.7 — remplacement du pack animé")
        except discord.Forbidden:
            logger.warning("Pack SentriX : suppression de %s refusée.", value.name)
            break
        except discord.HTTPException as exc:
            logger.warning("Pack SentriX : suppression de %s impossible : %s", value.name, exc)
            continue
        deleted_ids.add(value.id)
    if deleted_ids:
        logger.info("Pack SentriX : %s ancien(s) sxv36_* supprimé(s).", len(deleted_ids))
    return [value for value in current if value.id not in deleted_ids]


async def sync_pack(bot: commands.Bot) -> int:
    """Synchronise les dix emojis SentriX sur le serveur officiel."""
    async with _SYNC_LOCK:
        guild = await _resolve_official_guild(bot)
        if guild is None:
            logger.warning("Pack SentriX : serveur officiel introuvable ; synchronisation reportée.")
            return 0
        try:
            current = list(await guild.fetch_emojis())
        except (discord.Forbidden, discord.HTTPException):
            current = list(guild.emojis)
        current = await _delete_legacy_pack(guild, current)
        count = _refresh_registry(current)
        if count == len(PACK):
            bot._sentrix_animated_emojis_ready = True
            bot._sentrix_emoji_registry = dict(_REGISTRY)
            return count
        if not _can_manage_expressions(guild):
            logger.warning("Pack SentriX : permission Gérer les expressions manquante sur %s (%s).", guild.name, guild.id)
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
                logger.error("Pack SentriX : asset introuvable %s.", path)
                continue
            try:
                created = await guild.create_custom_emoji(name=name, image=data, reason="Pack UI SentriX")
            except discord.Forbidden:
                logger.warning("Pack SentriX : Discord refuse la création de %s.", name)
                break
            except discord.HTTPException as exc:
                logger.warning("Pack SentriX : création de %s impossible : %s", name, exc)
                continue
            _REGISTRY[key] = created
            existing_names.add(name)
        bot._sentrix_emoji_registry = dict(_REGISTRY)
        bot._sentrix_animated_emojis_ready = len(_REGISTRY) == len(PACK)
        logger.info("Pack SentriX synchronisé : %s/%s sur %s.", len(_REGISTRY), len(PACK), guild.name)
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

    def style_embed_v39(embed: discord.Embed, *args, **kwargs):
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

    def style_view_v39(view: discord.ui.View | None):
        return _decorate_view(original_view(view))

    premium_style.style_embed = style_embed_v39
    premium_style.style_view = style_view_v39
    _INSTALLED = True


def install(bot: commands.Bot) -> None:
    _install_visual_pipeline()
    _install_sync(bot)
    bot._sentrix_animated_emoji_pack_v37 = True
    bot._sentrix_clear_ui_emojis_v362 = True
    logger.info("SentriX V3.9 : emojis animés réservés aux états ; navigation simple active.")


__all__ = [
    "PACK",
    "LEGACY_PACK_PREFIXES",
    "CATEGORY_ICONS",
    "emoji",
    "emoji_text",
    "install",
    "sync_pack",
    "_clean_artifacts",
    "_decorate_embed",
    "_decorate_view",
    "_is_legacy_pack_emoji_name",
]
