"""Anti-répétition des journaux SentriX.

Les journaux de production étaient noyés : sur 500 lignes prélevées, 441 étaient
des WARNING et **aucune** n'était une ERROR. Une seule boucle morte y répétait le
même message toutes les 60 secondes, et chaque log Discord réussi produisait six à
dix lignes de trace. Une vraie panne n'y aurait pas été vue.

Ce filtre compresse les répétitions d'un MÊME message :

- ``CRITICAL`` passe toujours ;
- ``ERROR`` passe pour ses premières occurrences (plus nombreuses que pour un
  WARNING : une erreur doit se voir), puis la même erreur répétée en boucle est
  retenue pendant la fenêtre et résumée à sa réouverture — 500 fois la même trace
  n'aide personne et noie la suivante ;
- en dessous, les premières occurrences passent, puis les suivantes sont retenues
  pendant la fenêtre ;
- à la réouverture de la fenêtre, le message repasse en indiquant combien de
  répétitions ont été masquées : l'information n'est pas perdue, elle est résumée.

Le regroupement se fait sur le GABARIT du message (``record.msg``, avant
interpolation) et non sur le texte final : « Boucle relancée : %s.%s » répété pour
la même boucle est compressé, tandis que deux messages différents restent
indépendants.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

# Au-delà, le message est retenu jusqu'à la fin de la fenêtre.
OCCURRENCES_AVANT_COMPRESSION = 2
# Une erreur a droit à plus d'occurrences avant compression : elle est rare et
# importante ; mais la même erreur en boucle (une tâche cassée, une permission
# manquante sur chaque message) est compressée comme le reste.
OCCURRENCES_ERREUR_AVANT_COMPRESSION = 5
FENETRE_SECONDES = 120.0
# Garde-fou mémoire : un bot qui tourne des semaines ne doit pas accumuler de clés.
MAX_CLES_SUIVIES = 2000


@dataclass
class _Fenetre:
    debut: float
    vues: int = 1
    masquees: int = 0
    derniere: float = field(default=0.0)


class FiltreAntiRepetition(logging.Filter):
    """Compresse les journaux répétitifs (erreurs comprises), jamais CRITICAL."""

    def __init__(
        self,
        fenetre: float = FENETRE_SECONDES,
        occurrences: int = OCCURRENCES_AVANT_COMPRESSION,
        max_cles: int = MAX_CLES_SUIVIES,
        occurrences_erreur: int = OCCURRENCES_ERREUR_AVANT_COMPRESSION,
    ) -> None:
        super().__init__()
        self.fenetre = float(fenetre)
        self.occurrences = max(1, int(occurrences))
        self.occurrences_erreur = max(self.occurrences, int(occurrences_erreur))
        self.max_cles = max(16, int(max_cles))
        self._fenetres: dict[tuple, _Fenetre] = {}
        self._verrou = threading.Lock()

    def _purger(self, maintenant: float) -> None:
        """Retire les fenêtres inactives quand le suivi devient trop gros."""
        if len(self._fenetres) <= self.max_cles:
            return
        limite = maintenant - self.fenetre
        for cle in [c for c, f in self._fenetres.items() if f.derniere < limite]:
            self._fenetres.pop(cle, None)
        if len(self._fenetres) > self.max_cles:
            # Cas pathologique : on repart de zéro plutôt que de grossir sans fin.
            self._fenetres.clear()

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - API logging
        # CRITICAL n'est jamais compressé.
        if record.levelno >= logging.CRITICAL:
            return True
        seuil = self.occurrences_erreur if record.levelno >= logging.ERROR else self.occurrences

        # Une exception est regroupée par son gabarit de message ET son type d'exception :
        # deux erreurs différentes sous le même « Erreur inattendue » restent distinctes.
        exc_type = ""
        if record.exc_info and record.exc_info[0] is not None:
            exc_type = getattr(record.exc_info[0], "__name__", "")
        cle = (record.name, record.levelno, str(record.msg), exc_type)
        maintenant = time.monotonic()

        with self._verrou:
            self._purger(maintenant)
            fenetre = self._fenetres.get(cle)

            if fenetre is None or (maintenant - fenetre.debut) >= self.fenetre:
                masquees = fenetre.masquees if fenetre is not None else 0
                self._fenetres[cle] = _Fenetre(debut=maintenant, vues=1, masquees=0, derniere=maintenant)
                if masquees:
                    # L'information n'est pas perdue : elle est résumée. Les
                    # arguments restent intacts, donc l'interpolation %s marche.
                    record.msg = f"{record.msg}  [+{masquees} répétition(s) masquée(s)]"
                return True

            fenetre.vues += 1
            fenetre.derniere = maintenant
            if fenetre.vues <= seuil:
                return True
            fenetre.masquees += 1
            return False


_INSTALLE: FiltreAntiRepetition | None = None


def installer(
    fenetre: float = FENETRE_SECONDES,
    occurrences: int = OCCURRENCES_AVANT_COMPRESSION,
) -> FiltreAntiRepetition:
    """Pose le filtre sur les handlers racine. Idempotent."""
    global _INSTALLE
    if _INSTALLE is not None:
        return _INSTALLE

    filtre = FiltreAntiRepetition(fenetre=fenetre, occurrences=occurrences)
    racine = logging.getLogger()
    for handler in racine.handlers:
        handler.addFilter(filtre)
    if not racine.handlers:
        # Aucun handler encore posé : on filtre au niveau du logger racine.
        racine.addFilter(filtre)
    _INSTALLE = filtre
    return filtre


def reinitialiser() -> None:
    """Retire le filtre. Réservé aux tests."""
    global _INSTALLE
    if _INSTALLE is None:
        return
    racine = logging.getLogger()
    for handler in racine.handlers:
        handler.removeFilter(_INSTALLE)
    racine.removeFilter(_INSTALLE)
    _INSTALLE = None


__all__ = ["FiltreAntiRepetition", "installer", "reinitialiser"]
