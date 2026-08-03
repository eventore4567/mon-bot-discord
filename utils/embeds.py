"""Générateurs d'embeds cohérents pour tout le bot (tous les messages sont en français).

Identité visuelle : violet électrique (COLOR_BRAND), footer signé "SentriX", et un
petit générateur de barres de progression façon jauge futuriste (xp, confiance IA, etc.)
réutilisé par plusieurs cogs (levels, ai...).
"""

import discord
from datetime import datetime, timezone
from config import COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING, COLOR_INFO, COLOR_NEUTRAL, COLOR_BRAND

FOOTER_TEXT = "SentriX"
FOOTER_ICON = None  # défini dynamiquement au démarrage (main.py) une fois le bot connecté


def set_footer_icon(url: str) -> None:
    """Appelé une fois depuis main.py (on_ready) pour afficher l'avatar du bot dans le footer partout."""
    global FOOTER_ICON
    FOOTER_ICON = url


def set_footer_text(text: str) -> None:
    """Change le texte du footer affiché sur tous les embeds (commande /footer, propriétaire du bot)."""
    global FOOTER_TEXT
    FOOTER_TEXT = text or "SentriX"


def set_brand_color(color: int) -> None:
    """Change la couleur d'accent utilisée par embeds.brand() (commande /theme, propriétaire du bot)."""
    global COLOR_BRAND
    COLOR_BRAND = color


def _base(title: str, description: str, color: int) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    if FOOTER_ICON:
        embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    else:
        embed.set_footer(text=FOOTER_TEXT)
    return embed


def success(description: str, title: str = "✅ Succès") -> discord.Embed:
    return _base(title, description, COLOR_SUCCESS)


def error(description: str, title: str = "❌ Erreur") -> discord.Embed:
    return _base(title, description, COLOR_ERROR)


def warning(description: str, title: str = "⚠️ Attention") -> discord.Embed:
    return _base(title, description, COLOR_WARNING)


def info(description: str, title: str = "ℹ️ Information") -> discord.Embed:
    return _base(title, description, COLOR_INFO)


def neutral(title: str, description: str = "", color: int | None = None) -> discord.Embed:
    return _base(title, description, color if color else COLOR_NEUTRAL)


def brand(title: str, description: str = "") -> discord.Embed:
    """Embed signature SentriX (violet électrique), pour les écrans les plus visibles (aide, IA, tickets...)."""
    return _base(title, description, COLOR_BRAND)


def bar(value: float, maximum: float, length: int = 12, filled_char: str = "🟪", empty_char: str = "⬛") -> str:
    """Jauge visuelle façon futuriste (utilisée pour l'XP, la confiance IA, etc.)."""
    ratio = value / maximum if maximum else 0
    filled = max(0, min(length, round(length * ratio)))
    return filled_char * filled + empty_char * (length - filled)
