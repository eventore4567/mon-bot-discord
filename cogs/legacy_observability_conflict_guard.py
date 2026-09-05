"""Neutralise l'ancien observateur V9 incompatible avec le runtime ProductionPhase.

Deux couches historiques utilisent le meme nom de table ``production_command_metrics``
avec des schemas differents. ProductionPhase est la source actuelle des metriques horaires.
Quand Slash V7 charge sa compatibilite historique, ProductionObservabilityV9 tenterait
ensuite d'utiliser ce meme nom comme journal evenementiel et provoquerait des
``OperationalError`` sur des colonnes inexistantes.

Cette garde est chargee avant Slash V7 sur Railway et rend uniquement le ``setup`` de cet
ancien observateur inactif. Les autres modules V9 (contexte IA, saisons, conseiller de
moderation) restent charges normalement. Aucun catalogue ni permission n'est modifie.
"""
from __future__ import annotations

import logging

from discord.ext import commands

logger = logging.getLogger("bot.legacy-observability-conflict")


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_legacy_observability_conflict_guard", False):
        return

    from . import production_observability_v9

    current_setup = production_observability_v9.setup
    if not getattr(current_setup, "_sentrix_disabled_schema_collision", False):
        async def disabled_legacy_observability(runtime_bot: commands.Bot) -> None:
            # Si une autre ancienne couche l'a charge avant cette garde, on la retire pour
            # qu'elle ne continue pas a ecrire dans le schema ProductionPhase.
            existing = runtime_bot.get_cog("ProductionObservabilityV9")
            if existing is not None:
                await runtime_bot.remove_cog("ProductionObservabilityV9")
            return None

        disabled_legacy_observability._sentrix_disabled_schema_collision = True
        disabled_legacy_observability._sentrix_original = current_setup
        production_observability_v9.setup = disabled_legacy_observability

    bot._sentrix_legacy_observability_conflict_guard = True
    logger.info("Ancien observateur V9 neutralise : collision production_command_metrics supprimee.")


async def setup(bot: commands.Bot) -> None:
    install(bot)
    # Soundboard est volontairement isolé dans son propre cog. Le charger ici évite de
    # modifier le gros bootstrap principal tout en garantissant son chargement sur Railway,
    # où cette garde est déjà ajoutée après cogs.logs et cogs.configuration.
    if "cogs.soundboard_logs" not in bot.extensions:
        await bot.load_extension("cogs.soundboard_logs")
