"""Compteurs regroupés : additionner en mémoire, écrire en base toutes les N secondes.

09/11/2026 : « SentriX est lent ». Mesuré en production : chaque requête PostgreSQL
coûte 125 à 500 ms, et chaque message envoyé déclenchait plusieurs écritures de
compteurs à la suite (messages comptés, activité, quêtes, succès). Sous un salon
actif, ces écritures occupaient la base au détriment de tout le reste (IA comprise).

Un ``CompteurGroupe`` additionne les incréments par clé et appelle ``ecrire(cle, total)``
une seule fois par clé et par intervalle. Une écriture qui échoue est journalisée et
n'empêche pas les autres. ``vider()`` écrit tout de suite ce qui attend (fermeture).
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable, Hashable

logger = logging.getLogger("bot.compteur-groupe")


class CompteurGroupe:
    def __init__(
        self,
        ecrire: Callable[[Any, int], Awaitable[None]],
        *,
        intervalle: float = 10.0,
        nom: str = "compteur",
    ) -> None:
        self._ecrire = ecrire
        self.intervalle = float(intervalle)
        self.nom = nom
        self._en_attente: dict[Hashable, int] = defaultdict(int)
        self._tache: asyncio.Task | None = None

    def ajouter(self, cle: Hashable, n: int = 1) -> None:
        if n <= 0:
            return
        self._en_attente[cle] += int(n)
        if self._tache is None or self._tache.done():
            try:
                self._tache = asyncio.get_running_loop().create_task(
                    self._boucle(), name=f"sentrix:{self.nom}"
                )
            except RuntimeError:
                pass  # hors boucle (tests synchrones) : vider() écrira

    def en_attente(self) -> dict:
        return dict(self._en_attente)

    async def vider(self) -> int:
        """Écrit tout ce qui attend ; rend le nombre de clés écrites."""
        lot, self._en_attente = self._en_attente, defaultdict(int)
        for cle, total in lot.items():
            try:
                await self._ecrire(cle, total)
            except Exception:
                logger.exception("%s : écriture impossible pour %s (+%s)", self.nom, cle, total)
        return len(lot)

    async def _boucle(self) -> None:
        while self._en_attente:
            await asyncio.sleep(self.intervalle)
            await self.vider()

    async def fermer(self) -> None:
        if self._tache is not None and not self._tache.done():
            self._tache.cancel()
        await self.vider()


__all__ = ["CompteurGroupe"]
