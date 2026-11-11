"""Qui bloque la boucle d'événements, et où exactement (11/11/2026).

La production se plaignait de « requêtes DB lentes » toute la journée : des
UPSERT d'une seule ligne, sur une clé primaire, à 300 ms, 800 ms, parfois une
seconde. Impossible côté PostgreSQL.

La preuve était dans les journaux, à condition de lire deux lignes voisines :

    Requête DB lente : execute 1048.8ms — INSERT INTO message_counts ...
    Requête DB lente : execute 1048.4ms — UPDATE engagement_members ...

Deux requêtes différentes, sur deux tables différentes, à 0,4 ms d'écart. Elles
n'ont pas mis une seconde chacune : la BOUCLE D'ÉVÉNEMENTS était bloquée, et
elles sont reparties ensemble quand elle s'est débloquée. Le temps était mesuré
autour du ``await``, donc tout ce qui attendait pendant ce gel semblait lent —
et le message accusait la base, qui n'y était pour rien.

Un bot Discord est mono-tâche : pendant qu'une fonction synchrone travaille
(une image, un gros JSON, une expression régulière sur un long texte), RIEN
d'autre n'avance. Ni les commandes, ni l'AutoMod, ni les battements de cœur.

Ce module mesure ce gel et NOMME le coupable. Un fil dédié surveille un
battement que la boucle rafraîchit : quand elle cesse de répondre, le fil
photographie la pile d'appels du fil principal — c'est-à-dire la fonction en
train de bloquer, avec son fichier et sa ligne. Le fil n'est jamais bloqué,
lui, puisqu'il ne dépend pas de la boucle.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback
from collections import Counter

logger = logging.getLogger("bot.boucle")

#: Le battement doit être rafraîchi au moins aussi souvent, sinon tout semble bloqué.
INTERVALLE_BATTEMENT = 0.05
#: Pas de rapport en dessous : un ramasse-miettes ou une rafale d'E/S passe par là.
SEUIL_ALERTE = float(os.getenv("SENTRIX_BOUCLE_SEUIL", "0.4"))
#: Un même coupable n'est signalé qu'une fois par minute : un blocage répété
#: remplirait les journaux au lieu de les rendre lisibles.
SILENCE_PAR_COUPABLE = 60.0
#: Les cadres internes d'asyncio ne disent rien : on cherche le code de SentriX.
_IGNORES = ("asyncio/", "selectors.py", "threading.py", "/discord/")


class Sentinelle:
    """Surveille le gel de la boucle depuis un fil qui, lui, ne gèle pas."""

    def __init__(self) -> None:
        self._battement = time.monotonic()
        self._fil_principal = threading.main_thread().ident
        self._fil: threading.Thread | None = None
        self._arret = threading.Event()
        self.pire_gel = 0.0
        self.gels = 0
        self.coupables: Counter[str] = Counter()
        self._derniers_rapports: dict[str, float] = {}

    # ---------------------------------------------------------------- mesure
    def battre(self) -> None:
        """Appelé par la boucle. Tant qu'elle appelle, elle n'est pas bloquée."""
        self._battement = time.monotonic()

    def retard(self) -> float:
        """Depuis combien de temps la boucle n'a pas donné signe de vie."""
        return max(0.0, time.monotonic() - self._battement - INTERVALLE_BATTEMENT)

    # --------------------------------------------------------------- rapport
    def _pile_du_fil_principal(self) -> list[str]:
        cadres = sys._current_frames()
        cadre = cadres.get(self._fil_principal)
        if cadre is None:
            return []
        return traceback.format_stack(cadre)

    @staticmethod
    def coupable_probable(pile: list[str]) -> str:
        """La ligne la plus profonde qui appartient à SentriX, pas à ses librairies."""
        for ligne in reversed(pile):
            if not any(marque in ligne for marque in _IGNORES):
                return " ".join(ligne.split())[:200]
        return " ".join(pile[-1].split())[:200] if pile else "pile indisponible"

    def _signaler(self, retard: float) -> None:
        pile = self._pile_du_fil_principal()
        coupable = self.coupable_probable(pile)
        self.gels += 1
        self.pire_gel = max(self.pire_gel, retard)
        self.coupables[coupable] += 1
        instant = time.monotonic()
        precedent = self._derniers_rapports.get(coupable, 0.0)
        if instant - precedent < SILENCE_PAR_COUPABLE:
            return
        self._derniers_rapports[coupable] = instant
        logger.warning(
            "Boucle bloquée %.0f ms — %s (%s fois)", retard * 1000, coupable, self.coupables[coupable]
        )

    # ------------------------------------------------------------------- fil
    def _surveiller(self) -> None:
        while not self._arret.wait(INTERVALLE_BATTEMENT):
            try:
                retard = self.retard()
                if retard >= SEUIL_ALERTE:
                    self._signaler(retard)
                    # On attend la fin du gel avant de reprendre la surveillance,
                    # sinon un blocage de 3 s produirait soixante rapports.
                    while not self._arret.is_set() and self.retard() >= SEUIL_ALERTE:
                        time.sleep(INTERVALLE_BATTEMENT)
            except Exception:  # noqa: BLE001 — une sentinelle ne tombe jamais
                logger.debug("Sentinelle de boucle en échec", exc_info=True)

    def demarrer(self) -> None:
        if self._fil is not None and self._fil.is_alive():
            return
        self._arret.clear()
        self._fil = threading.Thread(
            target=self._surveiller, name="sentrix-boucle", daemon=True
        )
        self._fil.start()

    def arreter(self) -> None:
        self._arret.set()
        self._fil = None

    def etat(self) -> dict:
        return {
            "gels": self.gels,
            "pire_gel_ms": round(self.pire_gel * 1000, 1),
            "retard_actuel_ms": round(self.retard() * 1000, 1),
            "coupables": self.coupables.most_common(5),
        }


#: Une seule sentinelle par processus : plusieurs fils mesureraient la même chose.
sentinelle = Sentinelle()


def retard_de_la_boucle() -> float:
    """Le gel en cours, en secondes. 0 quand la boucle répond normalement."""
    return sentinelle.retard()


__all__ = ["Sentinelle", "retard_de_la_boucle", "sentinelle"]
