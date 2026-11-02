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
        f"🛡️ {_format_number(members)} membre{'s' if members != 1 else ''} protégé"
        f"{'s' if members != 1 else ''} • {_format_number(len(guild_list))} "
        f"serveur{'s' if len(guild_list) != 1 else ''}"
    )



def rotating_presence_text(guilds: Iterable[Any], phase: int = 0) -> str:
    """Affiche des compteurs réels en français/anglais, sans compter les membres uniques."""
    guild_list = list(guilds)
    members = sum(max(0, int(getattr(guild, "member_count", 0) or 0)) for guild in guild_list)
    servers = len(guild_list)
    member_fr = f"{_format_number(members)} membre{'s' if members != 1 else ''}"
    member_en = f"{_format_number(members)} member{'s' if members != 1 else ''}"
    server_fr = f"{_format_number(servers)} serveur{'s' if servers != 1 else ''}"
    server_en = f"{_format_number(servers)} server{'s' if servers != 1 else ''}"
    messages = (
        f"Protège {member_fr}",
        f"Protecting {member_en}",
        f"Actif sur {server_fr}",
        f"Active on {server_en}",
    )
    return messages[phase % len(messages)]
