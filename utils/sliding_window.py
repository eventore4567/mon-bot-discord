"""Compteur d'événements par clé sur une fenêtre de temps, qui oublie.

Les compteurs de l'AutoMod — spam, actions sensibles, infractions — étaient
quatre dictionnaires `{(serveur, membre): [horodatages]}` remplis à chaque
message et jamais vidés. Les horodatages, eux, étaient bien élagués : c'étaient
les CLÉS qui s'accumulaient. Une entrée par membre ayant parlé une seule fois,
conservée pour toujours, y compris après son départ du serveur.

Mesuré : 12,4 Mo pour 50 000 membres dans un seul compteur, ~50 Mo pour les
quatre, sans jamais redescendre. Sur un conteneur avec une limite de mémoire,
la fin de l'histoire est un OOM — et un bot tué, c'est un serveur sans
protection. La fuite était donc un problème de sécurité, pas de confort.

La purge est amortie sur les insertions plutôt que confiée à une tâche de fond :
une boucle asyncio de plus, c'est un mode de panne de plus, et il faudrait la
démarrer, l'arrêter et la surveiller. Ici, il n'y a rien à superviser.
"""
from __future__ import annotations

import time
from typing import Hashable


class FenetreGlissante:
    """Compte les événements récents par clé, et oublie les clés inactives.

    ``fenetre`` est en secondes. ``purge_toutes`` dit au bout de combien
    d'insertions on balaie les clés expirées : le balayage coûte O(clés), donc
    amorti sur N insertions il revient à O(clés/N) par événement.
    """

    __slots__ = ("fenetre", "purge_toutes", "_evenements", "_depuis_purge")

    def __init__(self, fenetre: float, purge_toutes: int = 1000) -> None:
        self.fenetre = float(fenetre)
        self.purge_toutes = max(1, int(purge_toutes))
        self._evenements: dict[Hashable, list[float]] = {}
        self._depuis_purge = 0

    def ajouter(self, cle: Hashable, maintenant: float | None = None) -> int:
        """Enregistre un événement et retourne le nombre d'événements dans la fenêtre."""
        instant = time.time() if maintenant is None else maintenant
        limite = instant - self.fenetre
        recents = [x for x in self._evenements.get(cle, ()) if x > limite]
        recents.append(instant)
        self._evenements[cle] = recents

        self._depuis_purge += 1
        if self._depuis_purge >= self.purge_toutes:
            self._purger(instant)
        return len(recents)

    def compter(self, cle: Hashable, maintenant: float | None = None) -> int:
        instant = time.time() if maintenant is None else maintenant
        limite = instant - self.fenetre
        return sum(1 for x in self._evenements.get(cle, ()) if x > limite)

    def reinitialiser(self, cle: Hashable) -> None:
        """Oublie complètement une clé — après une sanction, par exemple.

        La clé est retirée, pas remise à une liste vide : une liste vide reste
        une entrée de dictionnaire, et c'est exactement ce qui fuyait.
        """
        self._evenements.pop(cle, None)

    def vider(self) -> None:
        """Oublie toutes les clés. Utilisé par les audits pour repartir à zéro."""
        self._evenements.clear()
        self._depuis_purge = 0

    # Les compteurs étaient des dictionnaires : `clear()` est déjà appelé par
    # tools/security_runtime_audit. Garder le nom évite de casser un appelant
    # pour une question de vocabulaire.
    clear = vider

    def _purger(self, instant: float) -> None:
        limite = instant - self.fenetre
        self._evenements = {
            cle: horodatages
            for cle, horodatages in self._evenements.items()
            if horodatages and horodatages[-1] > limite
        }
        self._depuis_purge = 0

    def __len__(self) -> int:
        """Nombre de clés encore suivies — utilisé par les tests et le diagnostic."""
        return len(self._evenements)


__all__ = ["FenetreGlissante"]
