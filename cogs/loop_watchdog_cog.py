"""Branche utils/loop_watchdog : un module install()-seul ne tourne pas en
production, d'où un vrai setup() listé dans main.EXTENSIONS.

Lancé APRÈS on_ready (et 30 s de marge) : le chargement des modules bloque la
boucle plusieurs secondes à chaque démarrage, ce qui n'est pas la lenteur cherchée."""
from __future__ import annotations

import asyncio
import logging

from discord.ext import commands

from utils import loop_watchdog

logger = logging.getLogger("bot.loop-watchdog")


class LoopWatchdog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        # 12/11/2026 : le détecteur attendait que le bot soit prêt PLUS 30 secondes.
        # Les gels les plus gros sont ceux du démarrage — chargement des extensions,
        # import du SDK IA, génération des bannières — et c'étaient exactement ceux
        # qu'il ne voyait jamais. Mesuré le 11/11 : un gel de 1,28 s à 23:40:38,
        # alors que le détecteur n'est devenu actif qu'à 23:41:08. Pire, pendant
        # cette fenêtre l'observabilité lisait un retard nul et imputait le gel à
        # PostgreSQL, qui n'y était pour rien.
        #
        # Il démarre donc dès le chargement du cog. Pas de flot à craindre :
        # _surveiller ne signale qu'UNE fois par gel, pas une fois par sondage —
        # un démarrage chargé produit quelques lignes, et elles sont justement
        # celles qu'on cherchait.
        #
        # Pas d'écouteur on_ready de plus (budget d'écouteurs, test_runtime_hygiene_gates) :
        # cog_load est déjà asynchrone, la boucle tourne, rien d'autre n'est nécessaire.
        if loop_watchdog.demarrer(asyncio.get_running_loop()):
            logger.info(
                "Détecteur de blocage de boucle actif dès le chargement (seuil %.1f s).",
                loop_watchdog.SEUIL_S,
            )

    def cog_unload(self):
        loop_watchdog.arreter()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LoopWatchdog(bot))
