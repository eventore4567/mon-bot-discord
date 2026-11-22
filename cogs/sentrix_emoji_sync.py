"""Téléverse la bibliothèque d'icônes SentriX au démarrage, sans bloquer.

Les icônes sont des emojis d'APPLICATION : téléversées une fois sur le compte
du bot, elles s'affichent sur les 28 serveurs sans y occuper le moindre
emplacement. Voir ``utils/sentrix_emojis`` pour le détail de ce choix.

**Ce module ne doit jamais empêcher SentriX de démarrer.** Le premier
démarrage pousse plus de cent fichiers ; si Discord limite, si le réseau
tombe, ou si le jeton n'a pas la portée nécessaire, le bot continue et les
panneaux affichent les replis sobres. Un panneau sans icône reste utilisable ;
un bot qui ne démarre pas ne l'est pas.

La tâche part donc en arrière-plan après ``on_ready``, et toute exception y est
absorbée.
"""
from __future__ import annotations

import asyncio
import logging

from discord.ext import commands

from utils import sentrix_emojis

logger = logging.getLogger("bot.sentrix-emoji-sync")


class SentriXEmojiSync(commands.Cog):
    """Synchronise le pack d'icônes une fois la session Discord ouverte."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._tache: asyncio.Task | None = None

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # on_ready peut se déclencher plusieurs fois (reconnexion de gateway).
        # Sans cette garde, chaque reconnexion relancerait un balayage complet.
        if self._tache is not None and not self._tache.done():
            return
        self._tache = asyncio.create_task(
            self._synchroniser(), name="sentrix-emoji-sync"
        )

    async def _synchroniser(self) -> None:
        try:
            bilan = await sentrix_emojis.synchroniser(self.bot)
        except Exception:
            # Déjà absorbé dans synchroniser(), mais une tâche de fond qui
            # meurt sans trace est un angle mort : on le dit.
            logger.exception("Synchronisation des icônes SentriX interrompue.")
            return
        if bilan.get("echecs"):
            logger.warning(
                "Icônes SentriX : %s échec(s) de téléversement, replis actifs "
                "pour ces icônes.",
                bilan["echecs"],
            )

    async def cog_unload(self) -> None:
        if self._tache is not None and not self._tache.done():
            self._tache.cancel()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SentriXEmojiSync(bot))
