"""Fabrique visuelle officielle de SentriX.

Ce module est la source de vérité pour les embeds Discord : couleur, footer, bannière,
titres, dates et disposition des fields. Les anciennes fonctions publiques sont gardées
pour ne casser aucun cog historique.

Règle importante : les fonctions de nettoyage ne touchent qu'aux éléments d'interface
(titres, noms de fields, boutons). Les valeurs métier et contenus utilisateurs ne sont
jamais nettoyés d'emojis automatiquement.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Iterable

import discord

from config import COLOR_BRAND


SENTRIX_COLOR = int(COLOR_BRAND)
SENTRIX_FOOTER = "SentriX"
SENTRIX_BANNER_URL = (
    "https://raw.githubusercontent.com/eventore4567/mon-bot-discord/"
    "main/assets/sentrix/banner-v70.png"
)

FOOTER_TEXT = SENTRIX_FOOTER
FOOTER_ICON: str | None = None

_CUSTOM_EMOJI_RE = re.compile(r"<a?:[A-Za-z0-9_]{2,32}:\d+>")
_SPACE_RE = re.compile(r"[ \t]{2,}")


def _is_emoji_codepoint(code: int) -> bool:
    return (
        0x1F000 <= code <= 0x1FAFF
        or 0x2600 <= code <= 0x27BF
        or 0x2300 <= code <= 0x23FF
        or code in {0xFE0F, 0x200D}
    )


def clean_ui_text(value: Any, limit: int = 256, fallback: str = "") -> str:
    """Retire uniquement la décoration ajoutée par SentriX d'un libellé d'interface."""
    text = _CUSTOM_EMOJI_RE.sub("", str(value or ""))
    text = "".join(char for char in text if not _is_emoji_codepoint(ord(char)))
    text = _SPACE_RE.sub(" ", text.replace("\r", " ")).strip(" \n\t-•·|:/")
    if not text:
        text = fallback
    if len(text) > limit:
        text = text[: max(1, limit - 1)].rstrip() + "…"
    return text


def clip(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def set_footer_icon(url: str) -> None:
    global FOOTER_ICON
    FOOTER_ICON = str(url or "").strip() or None


def set_footer_text(text: str) -> None:
    global FOOTER_TEXT
    FOOTER_TEXT = clean_ui_text(text, 120, SENTRIX_FOOTER) or SENTRIX_FOOTER


def set_brand_color(color: int) -> None:
    global SENTRIX_COLOR
    SENTRIX_COLOR = int(color)
    # Compatibilité : premium_style lit encore son dictionnaire dans quelques anciens cogs.
    try:
        from utils import premium_style
        for key in list(premium_style.COLORS):
            premium_style.COLORS[key] = SENTRIX_COLOR
    except Exception:
        pass


def set_banner_url(url: str) -> None:
    global SENTRIX_BANNER_URL
    value = str(url or "").strip()
    if value:
        SENTRIX_BANNER_URL = value


def format_datetime_fr(value: datetime | None = None) -> str:
    dt = value or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%d/%m/%Y • %H:%M")


def _footer(embed: discord.Embed, text: str | None = None) -> discord.Embed:
    footer = clean_ui_text(text or FOOTER_TEXT, 160, SENTRIX_FOOTER) or SENTRIX_FOOTER
    if FOOTER_ICON:
        embed.set_footer(text=footer, icon_url=FOOTER_ICON)
    else:
        embed.set_footer(text=footer)
    return embed


def _base(
    title: str,
    description: str | None = None,
    *,
    banner: bool = False,
    thumbnail: str | None = None,
    timestamp: bool = False,
    footer: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=clean_ui_text(title, 90, "Information"),
        description=clip(description, 4096) if description else None,
        colour=discord.Colour(SENTRIX_COLOR),
        timestamp=datetime.now(timezone.utc) if timestamp else None,
    )
    if thumbnail:
        embed.set_thumbnail(url=str(thumbnail))
    if banner and SENTRIX_BANNER_URL:
        embed.set_image(url=SENTRIX_BANNER_URL)
    return _footer(embed, footer)


def standard(
    title: str,
    description: str = "",
    *,
    thumbnail: str | None = None,
    timestamp: bool = False,
) -> discord.Embed:
    return _base(title, description or None, thumbnail=thumbnail, timestamp=timestamp)


def large(
    title: str,
    description: str = "",
    *,
    thumbnail: str | None = None,
    timestamp: bool = False,
) -> discord.Embed:
    return _base(
        title,
        description or None,
        banner=True,
        thumbnail=thumbnail,
        timestamp=timestamp,
    )


def success(description: str, title: str = "Action effectuée") -> discord.Embed:
    return standard(clean_ui_text(title, 90, "Action effectuée"), description)


def error(description: str, title: str = "Erreur") -> discord.Embed:
    return standard(clean_ui_text(title, 90, "Erreur"), description)


def warning(description: str, title: str = "Vérification nécessaire") -> discord.Embed:
    return standard(clean_ui_text(title, 90, "Vérification nécessaire"), description)


def info(description: str, title: str = "Information") -> discord.Embed:
    return standard(clean_ui_text(title, 90, "Information"), description)


def neutral(title: str, description: str = "", color: int | None = None) -> discord.Embed:
    del color
    return standard(title, description)


def brand(title: str, description: str = "") -> discord.Embed:
    return standard(title, description)


def category(category_name: str, title: str, description: str = "") -> discord.Embed:
    del category_name
    return standard(title, description)


def panel(
    title: str,
    description: str = "",
    *,
    category_name: str = "configuration",
    thumbnail: str | None = None,
) -> discord.Embed:
    del category_name
    return large(title, description, thumbnail=thumbnail)


def help_embed(title: str = "Commandes", description: str = "") -> discord.Embed:
    return large(title, description)


def profile_embed(title: str = "Profil", description: str = "", *, thumbnail: str | None = None) -> discord.Embed:
    return large(title, description, thumbnail=thumbnail)


def _field_inline(name: str, value: str, requested: bool | None) -> bool:
    if requested is not None:
        return bool(requested)
    normalized = clean_ui_text(name, 80).casefold()
    long_labels = {
        "raison", "motif", "message", "contenu", "avant", "après", "apres",
        "description", "permissions", "changements", "transcript", "pièces jointes",
        "pieces jointes",
    }
    if normalized in long_labels:
        return False
    return len(str(value or "")) <= 120 and str(value or "").count("\n") <= 1


def add_fields(
    embed: discord.Embed,
    fields: Iterable[tuple[str, Any, bool | None] | tuple[str, Any]],
) -> discord.Embed:
    for item in fields:
        if len(item) == 2:
            name, value = item
            requested = None
        else:
            name, value, requested = item
        if value is None or str(value).strip() == "":
            continue
        safe_name = clean_ui_text(name, 256, "Information")
        raw_value = clip(value, 1024) or "—"
        embed.add_field(
            name=safe_name,
            value=raw_value,
            inline=_field_inline(safe_name, raw_value, requested),
        )
    return embed


def log_embed(
    title: str,
    *,
    fields: Iterable[tuple[str, Any, bool | None] | tuple[str, Any]] = (),
    description: str = "",
    event_time: datetime | None = None,
    banner: bool = True,
) -> discord.Embed:
    embed = _base(
        title,
        description or None,
        banner=banner,
        timestamp=False,
        footer=SENTRIX_FOOTER,
    )
    add_fields(embed, fields)
    # Date commune pour tous les journaux ; on l'ajoute seulement si elle n'existe pas déjà.
    if not any(clean_ui_text(field.name, 40).casefold() == "date" for field in embed.fields):
        embed.add_field(name="Date", value=format_datetime_fr(event_time), inline=True)
    return embed


def _who(entity: Any) -> str:
    if entity is None:
        return "Non disponible"
    mention = getattr(entity, "mention", None)
    entity_id = getattr(entity, "id", None)
    if mention and entity_id:
        return f"{mention}\n`{entity_id}`"
    if entity_id:
        return f"{entity}\n`{entity_id}`"
    return str(entity)


def log_entry(
    title: str,
    color: int | None = None,
    *,
    cible=None,
    cible_label: str = "Cible",
    acteur=None,
    acteur_label: str = "Modérateur",
    raison: str | None = None,
    extra: dict | None = None,
) -> discord.Embed:
    del color
    fields: list[tuple[str, Any, bool | None]] = []
    if cible is not None:
        fields.append((cible_label, _who(cible), True))
    if acteur is not None:
        fields.append((acteur_label, _who(acteur), True))
    if extra:
        for name, value in list(extra.items())[:20]:
            fields.append((name, value, None))
    if raison is not None:
        fields.append(("Raison", raison or "Aucune raison fournie", False))
    return log_embed(title, fields=fields)


def bar(
    value: float,
    maximum: float,
    length: int = 10,
    filled_char: str = "▰",
    empty_char: str = "▱",
) -> str:
    try:
        ratio = float(value) / float(maximum) if maximum else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        ratio = 0.0
    filled = max(0, min(length, round(length * max(0.0, min(1.0, ratio)))))
    return filled_char * filled + empty_char * (length - filled)
