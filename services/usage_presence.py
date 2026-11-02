"""Statut Discord automatique présentant l'utilisation réelle de SentriX."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _format_number(value: int) -> str:
    return f"{max(0, value):,}".replace(",", " ")


def usage_presence_text(guilds: Iterable[Any]) -> str:
    """Statut d'origine avec bouclier, nombre de membres et de serveurs."""
    guild_list = list(guilds)
    members = sum(max(0, int(getattr(guild, "member_count", 0) or 0)) for guild in guild_list)
    return (
        f"🛡️ {_format_number(members)} membre{'s' if members != 1 else ''} protégé"
        f"{'s' if members != 1 else ''} • {_format_number(len(guild_list))} "
        f"serveur{'s' if len(guild_list) != 1 else ''}"
    )


def rotating_presence_text(guilds: Iterable[Any], phase: int = 0) -> str:
    """Même statut détaillé qu'avant, alterné FR/EN toutes les 30 secondes.

    Les membres représentent la somme des effectifs, pas des utilisateurs uniques.
    """
    guild_list = list(guilds)
    if phase % 2 == 0:
        return usage_presence_text(guild_list)

    members = sum(max(0, int(getattr(guild, "member_count", 0) or 0)) for guild in guild_list)
    servers = len(guild_list)
    return (
        f"🛡️ {members:,} member{'s' if members != 1 else ''} protected • "
        f"{servers:,} server{'s' if servers != 1 else ''}"
    )
