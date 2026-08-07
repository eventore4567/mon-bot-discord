"""Fabrique d'embeds officielle et unique de SentriX.

Toutes les anciennes fonctions publiques sont conservées pour ne casser aucun cog. Le
rendu final est délégué à ``utils.premium_style`` afin que les centaines de commandes,
les panneaux et les logs partagent exactement la même identité visuelle.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import discord

from config import (
    COLOR_BRAND,
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_NEUTRAL,
    COLOR_SUCCESS,
    COLOR_WARNING,
)
from utils import premium_style

FOOTER_TEXT = "SentriX"
FOOTER_ICON: str | None = None


def set_footer_icon(url: str) -> None:
    global FOOTER_ICON
    FOOTER_ICON = str(url or "").strip() or None


def set_footer_text(text: str) -> None:
    global FOOTER_TEXT
    FOOTER_TEXT = str(text or "SentriX").strip() or "SentriX"


def set_brand_color(color: int) -> None:
    global COLOR_BRAND
    COLOR_BRAND = int(color)
    premium_style.COLORS["brand"] = int(color)
    premium_style.COLORS["configuration"] = int(color)


def _clip(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    return premium_style.clip(value, limit)


def _base(
    title: str,
    description: str | None,
    color: int,
    *,
    category: str | None = None,
    kind: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=premium_style.clean_title(title),
        description=_clip(description, 4096),
        colour=discord.Colour(color),
        timestamp=datetime.now(timezone.utc),
    )
    footer = _clip(FOOTER_TEXT, 2048) or "SentriX"
    if FOOTER_ICON:
        embed.set_footer(text=footer, icon_url=FOOTER_ICON)
    else:
        embed.set_footer(text=footer)
    return premium_style.style_embed(embed, category=category, kind=kind)


def success(description: str, title: str = "Action terminée") -> discord.Embed:
    return _base(title, description, COLOR_SUCCESS, kind="success")


def error(description: str, title: str = "Action impossible") -> discord.Embed:
    return _base(title, description, COLOR_ERROR, kind="danger")


def warning(description: str, title: str = "Vérification nécessaire") -> discord.Embed:
    return _base(title, description, COLOR_WARNING, kind="warning")


def info(description: str, title: str = "Information") -> discord.Embed:
    return _base(title, description, COLOR_INFO, kind="info")


def neutral(title: str, description: str = "", color: int | None = None) -> discord.Embed:
    return _base(title, description, color if color is not None else COLOR_NEUTRAL)


def brand(title: str, description: str = "") -> discord.Embed:
    return _base(title, description, COLOR_BRAND, category="brand")


def category(category_name: str, title: str, description: str = "") -> discord.Embed:
    """Nouvelle API recommandée pour les cogs ajoutés après la refonte."""
    colour = premium_style.COLORS.get(category_name, COLOR_BRAND)
    return _base(title, description, colour, category=category_name)


def panel(
    title: str,
    description: str = "",
    *,
    category_name: str = "configuration",
    thumbnail: str | None = None,
) -> discord.Embed:
    embed = category(category_name, title, description)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    return embed


def _who(entity: Any) -> str:
    if entity is None:
        return "Inconnu"
    mention = getattr(entity, "mention", None)
    entity_id = getattr(entity, "id", None)
    if mention and entity_id:
        return f"{mention}\n`{entity_id}`"
    if entity_id:
        return f"{entity}\n`{entity_id}`"
    return str(entity)


def log_entry(
    title: str,
    color: int,
    *,
    cible=None,
    cible_label: str = "Cible",
    acteur=None,
    acteur_label: str = "Responsable",
    raison: str | None = None,
    extra: dict | None = None,
) -> discord.Embed:
    embed = _base(title, None, color, category="logs")
    if cible is not None:
        embed.add_field(name=premium_style.clean_title(cible_label, "Cible"), value=_who(cible), inline=True)
    if acteur is not None:
        embed.add_field(name=premium_style.clean_title(acteur_label, "Responsable"), value=_who(acteur), inline=True)
    if raison is not None:
        embed.add_field(
            name="Motif",
            value=premium_style.clip(raison or "Aucun motif fourni", 1024),
            inline=False,
        )
    if extra:
        for name, value in list(extra.items())[:22]:
            embed.add_field(
                name=premium_style.clean_title(name, "Détail"),
                value=premium_style.clip(value, 1024) or "—",
                inline=False,
            )
    if cible is not None and hasattr(cible, "display_avatar"):
        embed.set_thumbnail(url=cible.display_avatar.url)
    return premium_style.style_embed(embed, category="logs", log_type="audit")


def bar(
    value: float,
    maximum: float,
    length: int = 10,
    filled_char: str = "▰",
    empty_char: str = "▱",
) -> str:
    """Jauge compacte et lisible, sans rangée d'emojis lourds."""
    try:
        ratio = float(value) / float(maximum) if maximum else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        ratio = 0.0
    filled = max(0, min(length, round(length * ratio)))
    return filled_char * filled + empty_char * (length - filled)
