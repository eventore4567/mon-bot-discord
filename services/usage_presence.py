"""Statut Discord automatique présentant l'utilisation réelle de SentriX."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _format_number(value: int) -> str:
    return f"{max(0, value):,}".replace(",", " ")


def usage_presence_text(guilds: Iterable[Any]) -> str:
    """Construit le texte public à partir des serveurs actuellement en cache."""
    guild_list = list(guilds)
    members = sum(max(0, int(getattr(guild, "member_count", 0) or 0)) for guild in guild_list)
    return (
        f"Utilisé par {_format_number(members)} membre{'s' if members != 1 else ''} "
        f"sur {_format_number(len(guild_list))} serveur{'s' if len(guild_list) != 1 else ''}"
    )

