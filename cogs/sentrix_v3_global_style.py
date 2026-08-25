"""SentriX V3.3 — finition visuelle globale premium.

Cette couche reste volontairement non destructive : elle ne change aucune permission,
aucune commande et aucune logique métier. Elle améliore uniquement la hiérarchie
visuelle finale des embeds et des composants après le moteur premium historique.

Objectifs V3.3 :
- petit header = SentriX + catégorie ;
- gros titre = action réellement effectuée ;
- moins de répétitions et de pavés ;
- couleurs d'état immédiatement compréhensibles ;
- boutons plus cohérents et lisibles sur mobile ;
- logs Secure Audit laissés totalement intacts.
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


def _asset_url(bot_user: Any) -> str | None:
    avatar = getattr(getattr(bot_user, "display_avatar", None), "url", None)
    return str(avatar) if avatar else None


def _category_label(category: str) -> str:
    return str(premium_style.CATEGORY_NAMES.get(category, "SentriX"))


def _compact_description(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = _MANY_BLANKS_RE.sub("\n\n", text)
    return premium_style.clip(text, 4096)


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

    # Si aucune action spécifique n'est disponible, le gros titre décrit l'état au lieu
    # de répéter une seconde fois « SentriX • Utilitaires » sous le header.
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
    """Nettoie uniquement l'espacement sans modifier la structure métier des champs."""
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

    # Les footers métier (pagination, références, etc.) restent intacts.
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

    # Les logs ont un renderer Secure Audit dédié. V3.3 n'y touche volontairement pas.
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

    def styled_v33(embed: discord.Embed, *args, **kwargs):
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

    def styled_view_v33(view: discord.ui.View | None):
        return _refine_view(original_view(view))

    premium_style.style_embed = styled_v33
    premium_style.style_view = styled_view_v33
    _INSTALLED = True
    logger.info("SentriX V3.3 : hiérarchie visuelle premium et composants raffinés actifs.")


__all__ = ["install"]
