"""Générateurs d'embeds cohérents pour tout le bot (tous les messages sont en français)."""

import discord
from datetime import datetime, timezone
from config import COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING, COLOR_INFO, COLOR_NEUTRAL

FOOTER_TEXT = "Bot Discord Tout-en-Un"


def _base(title: str, description: str, color: int) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
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
