"""Retire les commandes de utils/unused_commands.SUPPRIMEES au démarrage.

28/10/2026 (Jayden) : supprimer au moins 50 commandes plutôt que d'en ajouter.
Chaque nom est vérifié EXACTEMENT (get_command rend la racine quand la
sous-commande manque — voir la mémoire « get_command rend la racine ») : on ne
retire jamais une autre commande par erreur. Deux passes : au chargement, puis
une fois le bot prêt, car certaines couches ajoutent leurs commandes tard.
"""
from __future__ import annotations

import asyncio
import logging

from discord.ext import commands

from utils.unused_commands import OUTILS_PROPRIETAIRE_RETIRES, SUPPRIMEES

#: Commandes jamais utilisées (28/10) + outils du propriétaire global (29/10).
A_RETIRER = SUPPRIMEES | OUTILS_PROPRIETAIRE_RETIRES

logger = logging.getLogger("bot.commandes-retirees")


def retirer(bot: commands.Bot) -> list[str]:
    retirees = []
    for nom in sorted(A_RETIRER, key=lambda n: -n.count(" ")):
        commande = bot.get_command(nom)
        if commande is None or commande.qualified_name != nom:
            continue
        parent = commande.parent
        (parent.remove_command if parent is not None else bot.remove_command)(commande.name)
        retirees.append(nom)
    return retirees


class CommandesRetirees(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._tache: asyncio.Task | None = None

    async def cog_load(self) -> None:
        retirer(self.bot)
        self._tache = asyncio.create_task(self._seconde_passe(), name="sentrix:commandes-retirees")

    async def _seconde_passe(self) -> None:
        while not self.bot.is_ready():
            await asyncio.sleep(1)
        await asyncio.sleep(5)
        retirer(self.bot)
        restantes = [n for n in A_RETIRER if self.bot.get_command(n) is not None
                     and self.bot.get_command(n).qualified_name == n]
        logger.info("Commandes retirées : %s/%s absentes.", len(A_RETIRER) - len(restantes), len(A_RETIRER))

    def cog_unload(self):
        if self._tache is not None:
            self._tache.cancel()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CommandesRetirees(bot))
