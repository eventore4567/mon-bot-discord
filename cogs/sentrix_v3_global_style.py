"""SentriX V3.4 — deux formats visuels cohérents pour toutes les cartes.

La couche reste non destructive : aucune permission, commande ou logique métier n'est
modifiée. Les cartes ordinaires sont classées automatiquement dans deux familles :

- compact : erreurs, confirmations et actions rapides ;
- large : help, setup, profils, tickets et panneaux riches.

Discord calcule lui-même la hauteur finale selon la police, la largeur du client et les
retours à la ligne. V3.4 ne prétend donc pas imposer une hauteur en pixels, mais rend les
cartes de chaque famille visuellement symétriques grâce à une structure, des limites et
des emplacements de champs constants. Les logs Secure Audit restent intacts.
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

_CANONICAL_TITLE_RE = re.compile(r"^SentriX\s*•\s*.+$", re.IGNORECASE)
_LEADING_DETAIL_RE = re.compile(r"^\*\*(.{1,96}?)\*\*(?:\n+|$)")
_MANY_BLANKS_RE = re.compile(r"\n{3,}")
_ZWSP = "\u200b"

_GENERIC_STATE_TITLES = {
    "success": "Action réussie",
    "warning": "À vérifier",
    "danger": "Action impossible",
    "info": "Information",
}

_BUTTON_EMOJIS = (
    (("configurer", "configuration", "setup", "paramètre", "settings"), "⚙️"),
    (("enregistrer", "save", "sauvegarder"), "💾"),
    (("confirmer", "confirm", "valider", "verify"), "✅"),
    (("rechercher", "search"), "🔎"),
    (("actualiser", "refresh", "recharger"), "🔄"),
    (("support", "ticket"), "🎫"),
    (("dashboard", "tableau de bord"), "🌐"),
    (("inviter", "invite"), "➕"),
    (("retour", "back", "précédent", "precedent"), "⬅️"),
    (("suivant", "next"), "➡️"),
    (("fermer", "close", "annuler", "cancel"), "✖️"),
    (("supprimer", "delete", "effacer"), "🗑️"),
)

# Deux formats seulement. Les cartes qui contiennent naturellement beaucoup de données
# basculent automatiquement sur le grand format afin de ne rien couper.
_LARGE_COMMAND_HINTS = {
    "help", "setup", "profile", "profile-card", "userinfo", "botinfo",
    "ticketsetup", "ticket", "shoppanel", "shop", "inventory", "leaderboard-levels",
    "economyleaderboard", "command-stats", "server-growth", "security-check",
    "automod-status", "config-view", "rolepanel", "diagnostic", "bot-status",
}
_LARGE_CATEGORIES = {
    "configuration", "tickets", "profile", "shop", "leaderboard", "premium",
}
_SMALL_FIELD_SLOTS = 2
_LARGE_FIELD_SLOTS = 6
_SMALL_DESCRIPTION_LIMIT = 520
_LARGE_DESCRIPTION_LIMIT = 1800
_SMALL_FIELD_LIMIT = 280
_LARGE_FIELD_LIMIT = 700


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


def _promote_real_title(embed: discord.Embed, *, kind: str) -> None:
    """Transforme « SentriX • Catégorie » + **Action** en vraie hiérarchie premium."""
    current_title = str(getattr(embed, "title", "") or "").strip()
    description = _compact_description(getattr(embed, "description", None))

    if not _CANONICAL_TITLE_RE.match(current_title):
        embed.description = description
        return

    match = _LEADING_DETAIL_RE.match(description or "")
    if match:
        promoted = premium_style.clean_title(match.group(1), fallback="Information")
        if promoted and len(promoted) <= premium_style.VISUAL_LIMITS["title"]:
            embed.title = promoted
            remaining = (description or "")[match.end():].lstrip()
            embed.description = remaining or None
            return

    embed.title = _GENERIC_STATE_TITLES.get(kind, "Information")
    embed.description = description


def _set_premium_author(
    embed: discord.Embed,
    *,
    category: str,
    bot_user: Any,
) -> None:
    """Conserve les auteurs métier personnalisés ; harmonise seulement ceux de SentriX."""
    current = getattr(getattr(embed, "author", None), "name", None)
    current_text = str(current or "").strip()
    if current_text and not current_text.casefold().startswith("sentrix"):
        return

    label = _category_label(category)
    icon = _asset_url(bot_user)
    name = "SentriX" if category == "brand" else f"SentriX • {label}"
    if icon:
        embed.set_author(name=name, icon_url=icon)
    else:
        embed.set_author(name=name)


def _refine_fields(embed: discord.Embed) -> None:
    """Nettoie l'espacement sans modifier la structure métier des champs."""
    for index, field in enumerate(list(embed.fields)):
        name = premium_style.display_label(field.name, "Information")
        value = _compact_description(field.value) or "—"
        embed.set_field_at(
            index,
            name=premium_style.clip(name, 256),
            value=premium_style.clip(value, 1024),
            inline=bool(field.inline),
        )


def _refine_footer(embed: discord.Embed, *, category: str, guild: discord.Guild | None) -> None:
    footer = getattr(embed, "footer", None)
    footer_text = str(getattr(footer, "text", "") or "").strip()
    footer_icon = getattr(footer, "icon_url", None)

    generic = not footer_text or footer_text.casefold().startswith("sentrix")
    if not generic:
        return

    parts = ["SentriX"]
    if category not in {"brand", "utility"}:
        parts.append(_category_label(category))
    if guild is not None:
        parts.append(premium_style.clip(getattr(guild, "name", "Serveur"), 42))
    text = " • ".join(parts)
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
    """Retourne strictement `small` ou `large`."""
    command_name = _command_name(command)
    description = str(getattr(embed, "description", "") or "")

    if command_name in _LARGE_COMMAND_HINTS:
        return "large"
    if any(command_name.startswith(f"{name} ") for name in _LARGE_COMMAND_HINTS):
        return "large"
    if category in _LARGE_CATEGORIES:
        return "large"
    if _has_media(embed):
        return "large"
    if len(embed.fields) > _SMALL_FIELD_SLOTS:
        return "large"
    if len(description) > _SMALL_DESCRIPTION_LIMIT:
        return "large"
    return "small"


def _trim_field_value(value: Any, *, limit: int) -> str:
    text = _compact_description(value, limit=limit) or "—"
    return text


def _pad_field_slots(embed: discord.Embed, *, slots: int) -> None:
    """Réserve le même nombre de blocs sans afficher de texte artificiel."""
    if len(embed.fields) >= slots:
        return
    for _ in range(slots - len(embed.fields)):
        embed.add_field(name=_ZWSP, value=_ZWSP, inline=True)


def _apply_two_size_layout(embed: discord.Embed, *, size: str) -> None:
    """Normalise la densité visuelle selon l'un des deux formats SentriX."""
    if size == "large":
        description_limit = _LARGE_DESCRIPTION_LIMIT
        field_limit = _LARGE_FIELD_LIMIT
        slots = _LARGE_FIELD_SLOTS
        title_limit = 64
    else:
        description_limit = _SMALL_DESCRIPTION_LIMIT
        field_limit = _SMALL_FIELD_LIMIT
        slots = _SMALL_FIELD_SLOTS
        title_limit = 48

    if embed.title:
        embed.title = premium_style.clip(embed.title, title_limit)
    if embed.description:
        embed.description = _compact_description(embed.description, limit=description_limit)

    # Ne retire jamais un champ métier. Les cartes <= slots sont simplement complétées
    # par des emplacements invisibles pour conserver une silhouette stable.
    for index, field in enumerate(list(embed.fields)):
        if str(field.name) == _ZWSP and str(field.value) == _ZWSP:
            continue
        embed.set_field_at(
            index,
            name=premium_style.clip(field.name, 256),
            value=_trim_field_value(field.value, limit=field_limit),
            inline=bool(field.inline),
        )

    if len(embed.fields) <= slots:
        _pad_field_slots(embed, slots=slots)


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

    # Les logs ont un renderer Secure Audit dédié. V3.4 n'y touche volontairement pas.
    is_log = bool(log_type) or resolved_category == "logs"
    if is_log:
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
    _refine_footer(embed, category=resolved_category, guild=guild)
    return embed


def _safe_button_emoji(item: discord.ui.Button) -> None:
    """Ajoute seulement des emojis Unicode standards et uniquement quand le bouton n'en a pas."""
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
            _safe_button_emoji(item)
        elif isinstance(item, discord.ui.Select):
            placeholder = str(item.placeholder or "").strip()
            if not placeholder:
                item.placeholder = "Choisir une option…"
    return view


def install(bot: commands.Bot) -> None:
    del bot
    global _INSTALLED
    if _INSTALLED:
        return

    original_embed = premium_style.style_embed
    original_view = premium_style.style_view

    def styled_v34(embed: discord.Embed, *args, **kwargs):
        result = original_embed(embed, *args, **kwargs)
        if not isinstance(result, discord.Embed):
            return result
        return _refine_embed(
            result,
            command=kwargs.get("command"),
            guild=kwargs.get("guild"),
            requester=kwargs.get("requester"),
            bot_user=kwargs.get("bot_user"),
            category=kwargs.get("category"),
            kind=kwargs.get("kind"),
            log_type=kwargs.get("log_type"),
        )

    def styled_view_v34(view: discord.ui.View | None):
        return _refine_view(original_view(view))

    premium_style.style_embed = styled_v34
    premium_style.style_view = styled_view_v34
    _INSTALLED = True
    logger.info("SentriX V3.4 : cartes compactes/grandes symétriques actives.")


__all__ = ["install", "_layout_size", "_apply_two_size_layout"]
