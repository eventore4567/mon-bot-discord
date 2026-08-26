"""Correctif final du rendu +ping.

Cette couche neutralise l'ancien enrichissement de ``command_style_v2`` qui réajoutait
une barre de progression et des séparateurs après le renderer principal. Elle ne touche
à aucune logique métier.
"""
from __future__ import annotations

import discord

from . import command_style_v2

_INSTALLED = False


def _latency_quality(latency_ms: int) -> tuple[str, str]:
    """Conserve le contrat historique sans jamais retourner de barre visuelle."""
    if latency_ms <= 80:
        return "Excellente", ""
    if latency_ms <= 140:
        return "Très bonne", ""
    if latency_ms <= 220:
        return "Correcte", ""
    return "Dégradée", ""


def _enrich_ping(embed: discord.Embed, command) -> None:
    if command_style_v2._root_name(command) != "ping":
        return

    bot = getattr(getattr(command, "cog", None), "bot", None)
    if bot is None:
        return

    latency_ms = max(0, round(float(getattr(bot, "latency", 0.0)) * 1000))
    quality, _unused = _latency_quality(latency_ms)
    server_count = len(getattr(bot, "guilds", ()) or ())
    member_count = sum(
        int(getattr(guild, "member_count", 0) or 0)
        for guild in getattr(bot, "guilds", ()) or ()
    )
    shard_count = int(getattr(bot, "shard_count", None) or 1)
    active = not bool(getattr(bot, "is_closed", lambda: False)())

    if latency_ms <= 80:
        colour = command_style_v2.COLORS["success"]
    elif latency_ms <= 140:
        colour = command_style_v2.COLORS["info"]
    elif latency_ms <= 220:
        colour = command_style_v2.COLORS["warning"]
    else:
        colour = command_style_v2.COLORS["danger"]

    embed.title = "Ping"
    embed.description = (
        f"## Latence : **{latency_ms} ms**\n"
        f"**Qualité :** {quality}\n\n"
        f"**Connexion :** {'Active' if active else 'Hors ligne'}   •   "
        f"**État :** {'Opérationnel' if active else 'Indisponible'}\n"
        f"**Serveurs :** {server_count:,}   •   "
        f"**Membres :** {member_count:,}   •   **Shards :** {shard_count}"
    )
    embed.clear_fields()
    embed.colour = discord.Colour(colour)
    embed.set_footer(text="SentriX • Mesure en temps réel")


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # Supprime aussi le long séparateur ━━━ injecté par l'ancienne couche.
    command_style_v2.BAR = ""
    command_style_v2._latency_quality = _latency_quality
    command_style_v2._enrich_ping = _enrich_ping
    _INSTALLED = True


install()
