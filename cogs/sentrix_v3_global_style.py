"""SentriX V3.10 — contrat visuel uniforme, compact et sans répétition.

Cette couche est uniquement visuelle. Elle ne modifie ni permissions, ni commandes, ni
logique métier. Une réponse doit avoir une hiérarchie unique : titre -> courte explication
-> blocs utiles -> contrôles. Les anciens champs vides, répétitions et grilles artificielles
sont supprimés. Les logs Secure Audit restent totalement exclus de cette transformation.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import discord
from discord.ext import commands

from utils import premium_style

logger = logging.getLogger("bot.sentrix-v3-global-style")
_INSTALLED = False

_CANONICAL_TITLE_RE = re.compile(r"^SentriX\s*•\s*(.+)$", re.IGNORECASE)
_LEADING_DETAIL_RE = re.compile(r"^\*\*(.{1,96}?)\*\*(?:\n+|$)")
_MANY_BLANKS_RE = re.compile(r"\n{3,}")
_DECORATIVE_TITLE_RE = re.compile(r"^[\s\u200b]*(?:[^\wÀ-ÿ]{1,4}\s*)+")
_MARKDOWN_RE = re.compile(r"[*_`~>|#]+")
_SPACE_RE = re.compile(r"\s+")
_ZWSP = "\u200b"

_GENERIC_STATE_TITLES = {
    "success": "Action réussie",
    "warning": "À vérifier",
    "danger": "Action impossible",
    "info": "Information",
}
_GENERIC_FIELD_NAMES = {
    "information", "informations", "details", "détails", "detail", "détail",
    "resume", "résumé", "aperçu", "apercu", "description", "etat", "état",
}

_BUTTON_EMOJIS = (
    (("configurer", "configuration", "setup", "paramètre", "settings"), "⚙️"),
    (("enregistrer", "save", "sauvegarder"), "💾"),
    (("confirmer", "confirm", "valider", "verify"), "✅"),
    (("rechercher", "search"), "🔎"),
    (("actualiser", "refresh", "recharger"), "🔄"),
    (("support", "ticket"), "🎫"),
    (("sécurité", "security"), "🛡️"),
    (("modération", "moderation"), "🔨"),
    (("dashboard", "tableau de bord"), "🌐"),
    (("inviter", "invite"), "➕"),
    (("retour", "back", "précédent", "precedent"), "⬅️"),
    (("suivant", "next"), "➡️"),
    (("fermer", "close", "annuler", "cancel"), "❌"),
    (("supprimer", "delete", "effacer"), "🗑️"),
)

_PANEL_COMMAND_HINTS = {
    "help", "setup", "profile", "profile-card", "userinfo", "botinfo",
    "ticketsetup", "ticket", "shoppanel", "shop", "inventory", "leaderboard-levels",
    "economyleaderboard", "command-stats", "server-growth", "security-check",
    "automod-status", "config-view", "rolepanel", "diagnostic", "bot-status",
    "security", "antiraid", "antinuke", "giveaway", "warnings",
}
_PANEL_CATEGORIES = {
    "configuration", "tickets", "profile", "shop", "leaderboard", "premium",
    "security", "moderation",
}

_COMPACT_DESCRIPTION_LIMIT = 420
_PANEL_DESCRIPTION_LIMIT = 900
_COMPACT_FIELD_LIMIT = 240
_PANEL_FIELD_LIMIT = 520
_PANEL_TITLE_LIMIT = 52
_COMPACT_TITLE_LIMIT = 42


def _asset_url(bot_user: Any) -> str | None:
    avatar = getattr(getattr(bot_user, "display_avatar", None), "url", None)
    return str(avatar) if avatar else None


def _category_label(category: str) -> str:
    return str(premium_style.CATEGORY_NAMES.get(category, "SentriX"))


def _compact_description(value: Any, *, limit: int = 4096) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = _MANY_BLANKS_RE.sub("\n\n", text)
    return premium_style.clip(text, limit)


def _semantic_text(value: Any) -> str:
    """Forme stable utilisée seulement pour détecter les répétitions visuelles."""
    text = str(value or "").replace(_ZWSP, " ")
    text = _CANONICAL_TITLE_RE.sub(r"\1", text)
    text = _DECORATIVE_TITLE_RE.sub("", text)
    text = _MARKDOWN_RE.sub("", text)
    text = re.sub(r"[^\wÀ-ÿ]+", " ", text, flags=re.UNICODE)
    return _SPACE_RE.sub(" ", text).strip().casefold()


def _dedupe_description(value: Any) -> str | None:
    """Supprime les paragraphes identiques empilés par plusieurs runtimes historiques."""
    text = _compact_description(value)
    if not text:
        return None
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    seen: set[str] = set()
    kept: list[str] = []
    for block in blocks:
        key = _semantic_text(block)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        kept.append(block)
    return "\n\n".join(kept) or None


def _clean_panel_title(value: Any, *, fallback: str) -> str:
    text = premium_style.clean_title(value, fallback=fallback)
    text = _DECORATIVE_TITLE_RE.sub("", text).strip()
    return premium_style.clip(text or fallback, _PANEL_TITLE_LIMIT)


def _promote_real_title(embed: discord.Embed, *, kind: str) -> None:
    current_title = str(getattr(embed, "title", "") or "").strip()
    description = _dedupe_description(getattr(embed, "description", None))

    canonical = _CANONICAL_TITLE_RE.match(current_title)
    if canonical is None:
        if current_title:
            embed.title = _clean_panel_title(current_title, fallback="Information")
        embed.description = description
        return

    match = _LEADING_DETAIL_RE.match(description or "")
    if match:
        promoted = _clean_panel_title(match.group(1), fallback="Information")
        if promoted:
            embed.title = promoted
            embed.description = (description or "")[match.end():].lstrip() or None
            return

    if kind == "info":
        embed.title = _clean_panel_title(canonical.group(1), fallback="Information")
    else:
        embed.title = _GENERIC_STATE_TITLES.get(kind, "Information")
    embed.description = description


def _set_premium_author(embed: discord.Embed, *, category: str, bot_user: Any) -> None:
    del category
    current = getattr(getattr(embed, "author", None), "name", None)
    current_text = str(current or "").strip()
    if current_text and not current_text.casefold().startswith("sentrix"):
        return
    icon = _asset_url(bot_user)
    if icon:
        embed.set_author(name="SentriX", icon_url=icon)
    else:
        embed.set_author(name="SentriX")


def _is_blank_field(name: Any, value: Any) -> bool:
    return not str(name or "").replace(_ZWSP, "").strip() and not str(value or "").replace(_ZWSP, "").strip()


def _refine_fields(embed: discord.Embed) -> None:
    """Nettoie et déduplique les champs sans jamais en ajouter."""
    description_key = _semantic_text(getattr(embed, "description", ""))
    title_key = _semantic_text(getattr(embed, "title", ""))
    seen: set[tuple[str, str]] = set()
    refined: list[tuple[str, str, bool]] = []

    for field in list(embed.fields):
        if _is_blank_field(field.name, field.value):
            continue
        name = premium_style.display_label(field.name, "Information")
        value = _dedupe_description(field.value) or "—"
        name_key = _semantic_text(name)
        value_key = _semantic_text(value)

        # Un champ « Information/Résumé » qui répète la description n'apporte rien.
        if name_key in _GENERIC_FIELD_NAMES and value_key and value_key == description_key:
            continue
        # Même règle quand un ancien renderer a recopié le titre comme champ avec la même
        # information déjà présente dans le corps.
        if name_key == title_key and value_key and value_key == description_key:
            continue

        signature = (name_key, value_key)
        if signature in seen:
            continue
        seen.add(signature)
        refined.append((premium_style.clip(name, 256), premium_style.clip(value, 1024), bool(field.inline)))

    embed.clear_fields()
    for name, value, inline in refined:
        embed.add_field(name=name, value=value, inline=inline)


def _dedupe_title_field(embed: discord.Embed) -> None:
    """Un titre ne doit jamais réapparaître comme première section juste en dessous."""
    title_key = _semantic_text(getattr(embed, "title", ""))
    if not title_key or not embed.fields:
        return

    body = str(getattr(embed, "description", "") or "").strip()
    body_key = _semantic_text(body)
    rebuilt: list[tuple[str, str, bool]] = []
    for field in list(embed.fields):
        name = str(field.name or "").strip()
        value = str(field.value or "").strip()
        name_key = _semantic_text(name)
        value_key = _semantic_text(value)
        if name_key == title_key:
            # On conserve l'information du champ uniquement si elle n'existe pas déjà.
            if value and value != "—" and value_key and value_key != body_key:
                body = f"{body}\n\n{value}".strip()
                body_key = _semantic_text(body)
            continue
        rebuilt.append((name, value or "—", bool(field.inline)))

    embed.description = _dedupe_description(body)
    embed.clear_fields()
    for name, value, inline in rebuilt:
        embed.add_field(name=name, value=value, inline=inline)


def _refine_footer(embed: discord.Embed, *, category: str, guild: discord.Guild | None) -> None:
    footer = getattr(embed, "footer", None)
    footer_text = str(getattr(footer, "text", "") or "").strip()
    footer_icon = getattr(footer, "icon_url", None)
    if footer_text and not footer_text.casefold().startswith("sentrix"):
        return

    parts: list[str] = []
    if category not in {"brand", "utility"}:
        parts.append(_category_label(category))
    if guild is not None:
        parts.append(premium_style.clip(getattr(guild, "name", "Serveur"), 38))
    text = " • ".join(parts) if parts else "SentriX"
    if footer_icon:
        embed.set_footer(text=text, icon_url=footer_icon)
    else:
        embed.set_footer(text=text)


def _command_name(command: Any) -> str:
    return str(getattr(command, "qualified_name", "") or "").casefold().strip()


def _has_media(embed: discord.Embed) -> bool:
    thumbnail = str(getattr(getattr(embed, "thumbnail", None), "url", "") or "")
    image = str(getattr(getattr(embed, "image", None), "url", "") or "")
    return bool(thumbnail or image)


def _layout_size(embed: discord.Embed, *, command: Any, category: str) -> str:
    command_name = _command_name(command)
    description = str(getattr(embed, "description", "") or "")
    if command_name in _PANEL_COMMAND_HINTS or any(command_name.startswith(f"{name} ") for name in _PANEL_COMMAND_HINTS):
        return "panel"
    if category in _PANEL_CATEGORIES or _has_media(embed):
        return "panel"
    if len(embed.fields) >= 3 or len(description) > _COMPACT_DESCRIPTION_LIMIT:
        return "panel"
    return "compact"


def _field_should_be_inline(name: str, value: str, *, original_inline: bool) -> bool:
    if not original_inline:
        return False
    if len(value) > 105 or value.count("\n") > 1:
        return False
    if "```" in value or len(name) > 28:
        return False
    return True


def _apply_compact_layout(embed: discord.Embed) -> None:
    if embed.title:
        embed.title = premium_style.clip(embed.title, _COMPACT_TITLE_LIMIT)
    embed.description = _compact_description(embed.description, limit=_COMPACT_DESCRIPTION_LIMIT)
    rebuilt: list[tuple[str, str, bool]] = []
    for field in list(embed.fields):
        if _is_blank_field(field.name, field.value):
            continue
        value = _compact_description(field.value, limit=_COMPACT_FIELD_LIMIT) or "—"
        rebuilt.append((premium_style.clip(field.name, 72), value, False))
    embed.clear_fields()
    for name, value, inline in rebuilt[:3]:
        embed.add_field(name=name, value=value, inline=inline)


def _apply_panel_layout(embed: discord.Embed) -> None:
    if embed.title:
        embed.title = premium_style.clip(embed.title, _PANEL_TITLE_LIMIT)
    embed.description = _compact_description(embed.description, limit=_PANEL_DESCRIPTION_LIMIT)
    rebuilt: list[tuple[str, str, bool]] = []
    for field in list(embed.fields):
        if _is_blank_field(field.name, field.value):
            continue
        name = premium_style.clip(field.name, 64)
        value = _compact_description(field.value, limit=_PANEL_FIELD_LIMIT) or "—"
        inline = _field_should_be_inline(name, value, original_inline=bool(field.inline))
        rebuilt.append((name, value, inline))
    embed.clear_fields()
    for name, value, inline in rebuilt[:6]:
        embed.add_field(name=name, value=value, inline=inline)


def _apply_two_size_layout(embed: discord.Embed, *, size: str) -> None:
    if size in {"large", "panel"}:
        _apply_panel_layout(embed)
    else:
        _apply_compact_layout(embed)


def _refine_embed(
    embed: discord.Embed,
    *,
    command: Any = None,
    guild: discord.Guild | None = None,
    requester: Any = None,
    bot_user: Any = None,
    category: str | None = None,
    kind: str | None = None,
    log_type: str | None = None,
) -> discord.Embed:
    del requester
    resolved_category = premium_style.infer_category(command=command, embed=embed, hint=category)
    resolved_kind = kind or premium_style.infer_kind(embed)
    if bool(log_type) or resolved_category == "logs":
        return embed

    _set_premium_author(embed, category=resolved_category, bot_user=bot_user)
    _promote_real_title(embed, kind=resolved_kind)
    _refine_fields(embed)

    state_colours = {
        "success": premium_style.COLORS["success"],
        "warning": premium_style.COLORS["warning"],
        "danger": premium_style.COLORS["danger"],
    }
    if resolved_kind in state_colours:
        embed.colour = discord.Colour(state_colours[resolved_kind])
    elif resolved_category in premium_style.COLORS:
        embed.colour = discord.Colour(premium_style.COLORS[resolved_category])

    size = _layout_size(embed, command=command, category=resolved_category)
    _apply_two_size_layout(embed, size=size)
    _dedupe_title_field(embed)
    embed.description = _dedupe_description(embed.description)
    _refine_footer(embed, category=resolved_category, guild=guild)
    return embed


def _safe_button_emoji(item: discord.ui.Button) -> None:
    if item.emoji is not None or not item.label:
        return
    haystack = f"{item.label} {item.custom_id or ''}".casefold()
    for words, emoji in _BUTTON_EMOJIS:
        if any(word in haystack for word in words):
            try:
                item.emoji = emoji
            except (TypeError, ValueError):
                pass
            return


def _refine_view(view: discord.ui.View | None) -> discord.ui.View | None:
    if view is None:
        return None
    for item in list(getattr(view, "children", ()) or ()):
        if isinstance(item, discord.ui.Button):
            label = str(item.label or "").strip()
            if label:
                item.label = premium_style.clip(label, premium_style.VISUAL_LIMITS["button_label"])
            _safe_button_emoji(item)
        elif isinstance(item, discord.ui.Select):
            placeholder = str(item.placeholder or "").strip()
            item.placeholder = premium_style.clip(placeholder or "Choisis une option…", premium_style.VISUAL_LIMITS["select_label"])
    return view


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if not _INSTALLED:
        original_embed = premium_style.style_embed
        original_view = premium_style.style_view

        def styled_v310(embed: discord.Embed, *args, **kwargs):
            result = original_embed(embed, *args, **kwargs)
            if not isinstance(result, discord.Embed):
                return result
            return _refine_embed(
                result,
                command=kwargs.get("command"), guild=kwargs.get("guild"),
                requester=kwargs.get("requester"), bot_user=kwargs.get("bot_user"),
                category=kwargs.get("category"), kind=kwargs.get("kind"),
                log_type=kwargs.get("log_type"),
            )

        def styled_view_v310(view: discord.ui.View | None):
            return _refine_view(original_view(view))

        premium_style.style_embed = styled_v310
        premium_style.style_view = styled_view_v310
        _INSTALLED = True
        logger.info("SentriX V3.10 : hiérarchie visuelle unique et déduplication globale actives.")

    try:
        from .sentrix_emoji_runtime import install as install_animated_emoji_pack
        install_animated_emoji_pack(bot)
    except Exception:
        logger.exception("Impossible d'installer le pack animé SentriX.")


__all__ = [
    "install", "_layout_size", "_apply_two_size_layout", "_refine_embed",
    "_dedupe_description", "_semantic_text",
]
