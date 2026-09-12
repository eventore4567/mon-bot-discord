"""Alimente core/observability/metrics.py — Core V2, Phase 1.

Écoute passive uniquement : ce cog n'intercepte, ne remplace et ne retarde
aucune commande. Il utilise exactement le même triplet d'événements
(``on_command`` / ``on_command_completion`` / ``on_command_error``) déjà
utilisé de façon éprouvée par cogs/production_phase_runtime.py dans ce dépôt —
aucun nouveau motif, juste une seconde consommatrice indépendante des mêmes
signaux discord.py natifs (aucun monkeypatch).

``ctx.interaction is not None`` distingue les deux transports pour une même
commande hybride, exactement comme le reste du dépôt le fait déjà ailleurs.
"""
from __future__ import annotations

import time

from discord.ext import commands

from core.observability import metrics


def _transport(ctx: commands.Context) -> str:
    return "slash" if getattr(ctx, "interaction", None) is not None else "prefix"


def _command_name(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    return str(getattr(command, "qualified_name", None) or "inconnue")


class CoreCommandObservability(commands.Cog, name="CoreCommandObservability"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context) -> None:
        setattr(ctx, "_core_obs_started", time.perf_counter())

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context) -> None:
        started = getattr(ctx, "_core_obs_started", None)
        elapsed_ms = (time.perf_counter() - started) * 1000.0 if started else 0.0
        metrics.record(_command_name(ctx), _transport(ctx), elapsed_ms, success=True)

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        metrics.record_error(_command_name(ctx), _transport(ctx))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CoreCommandObservability(bot))
