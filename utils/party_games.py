"""Règles pures des jeux à plusieurs : ``+race``, ``+detective``, ``+crown``.

Aucun import Discord. Ce qui est ici se simule par milliers de parties, et
c'est la seule façon de vérifier les deux promesses qui ne se voient pas en
cliquant : qu'une enquête désigne toujours exactement un coupable, et qu'une
course ne se gagne pas uniquement à la vitesse de clic.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# =============================================================================
# 🏁 RACE — avancer sûrement ou sprinter
# =============================================================================

PISTE = 24
AVANCE = (1, 3)              # pas garantis
SPRINT = (0, 8)              # pas risqués : espérance 2,15 contre 2,00, variance bien plus haute
SPRINT_RATE = 0.30           # part des sprints qui ne donnent rien
SPRINT_PENALITE = 1          # tours de repos après un sprint raté
DELAI_ENTRE_COUPS = 1.0      # secondes, par joueur
RACE_JOUEURS_MIN, RACE_JOUEURS_MAX = 2, 10
RACE_BASE = 60               # récompense du vainqueur
RACE_PARTICIPATION = 12


@dataclass
class Coureur:
    user_id: int
    position: int = 0
    repos: int = 0            # tours de pénalité restants
    sprints: int = 0
    coups: int = 0

    @property
    def arrive(self) -> bool:
        return self.position >= PISTE


def avancer(coureur: Coureur, sprinte: bool, alea) -> dict:
    """Résout un coup. Le sprint paie mieux en moyenne mais cale trois fois sur dix.

    Sans le repos après un sprint raté, sprinter serait toujours optimal : on
    perdrait seulement un tirage au lieu d'un tour, et l'espérance resterait
    supérieure à celle du pas garanti.
    """
    if coureur.repos > 0:
        coureur.repos -= 1
        coureur.coups += 1
        return {"pas": 0, "cale": False, "repos": True, "sprint": sprinte}
    if sprinte:
        coureur.sprints += 1
        if alea.chance(SPRINT_RATE):
            coureur.repos = SPRINT_PENALITE
            coureur.coups += 1
            return {"pas": 0, "cale": True, "repos": False, "sprint": True}
        pas = alea.entier(*SPRINT)
    else:
        pas = alea.entier(*AVANCE)
    coureur.position = min(PISTE, coureur.position + pas)
    coureur.coups += 1
    return {"pas": pas, "cale": False, "repos": False, "sprint": sprinte}


def esperance(sprinte: bool) -> float:
    """Pas attendus par coup joué, pénalité de repos comprise."""
    if not sprinte:
        return sum(AVANCE) / 2
    gain = sum(SPRINT) / 2
    coups = 1 + SPRINT_RATE * SPRINT_PENALITE
    return (1 - SPRINT_RATE) * gain / coups


# =============================================================================
# 🕵️ DETECTIVE — les indices doivent désigner exactement un suspect
# =============================================================================

ATTRIBUTS: dict[str, tuple[tuple[str, str], ...]] = {
    "veste": (("rouge", "🟥"), ("bleue", "🟦"), ("verte", "🟩"), ("noire", "⬛")),
    "accessoire": (("un chapeau", "🎩"), ("des lunettes", "👓"),
                   ("une écharpe", "🧣"), ("une canne", "🦯")),
    "lieu": (("la bibliothèque", "📚"), ("le jardin", "🌳"),
             ("la cuisine", "🍳"), ("le salon", "🛋️")),
}
PRENOMS = ("Adèle", "Basile", "Camille", "Damien", "Élise", "Fabien",
           "Gaëlle", "Hugo", "Inès", "Julien")

SUSPECTS = 6
INDICES_MAX = 8
DETECTIVE_JOUEURS_MIN, DETECTIVE_JOUEURS_MAX = 2, 12
DETECTIVE_BASE = 55
DETECTIVE_BONUS_PAR_INDICE_NON_LU = 12   # accuser tôt paie plus


@dataclass(frozen=True)
class Suspect:
    nom: str
    traits: tuple[tuple[str, str], ...]   # (attribut, valeur)

    def valeur(self, attribut: str) -> str:
        return dict(self.traits)[attribut]

    def portrait(self) -> str:
        pictos = {a: dict(ATTRIBUTS[a])[v] for a, v in self.traits}
        return (f"**{self.nom}** — veste {pictos['veste']} · porte "
                f"{pictos['accessoire']} · vu·e dans {pictos['lieu']}")


@dataclass(frozen=True)
class Indice:
    attribut: str
    valeur: str
    positif: bool

    def texte(self) -> str:
        picto = dict(ATTRIBUTS[self.attribut])[self.valeur]
        sujets = {
            "veste": ("portait une veste", "ne portait pas de veste"),
            "accessoire": ("portait", "ne portait pas"),
            "lieu": ("a été vu·e dans", "n'a pas été vu·e dans"),
        }[self.attribut]
        return f"Le coupable {sujets[0 if self.positif else 1]} {self.valeur} {picto}"

    def compatible(self, suspect: Suspect) -> bool:
        egal = suspect.valeur(self.attribut) == self.valeur
        return egal if self.positif else not egal


@dataclass(frozen=True)
class Enquete:
    suspects: tuple[Suspect, ...]
    coupable: Suspect
    indices: tuple[Indice, ...]

    def restants(self, indices_lus: int) -> list[Suspect]:
        lus = self.indices[:indices_lus]
        return [s for s in self.suspects if all(i.compatible(s) for i in lus)]


def compatibles(suspects, indices) -> list[Suspect]:
    return [s for s in suspects if all(i.compatible(s) for i in indices)]


def _tirer_suspects(alea) -> list[Suspect]:
    """Des suspects distincts : deux identiques rendraient l'enquête insoluble."""
    noms = list(PRENOMS)
    choisis: list[Suspect] = []
    vus: set[tuple] = set()
    garde = 0
    while len(choisis) < SUSPECTS and garde < 400:
        garde += 1
        traits = tuple(
            (attribut, alea.choix([v for v, _p in valeurs]))
            for attribut, valeurs in ATTRIBUTS.items()
        )
        if traits in vus:
            continue
        vus.add(traits)
        choisis.append(Suspect(noms[len(choisis)], traits))
    return choisis


def generer_enquete(alea, *, essais: int = 200) -> Enquete | None:
    """Tire une enquête et ne la rend que si ses indices désignent UN coupable.

    Comme pour le lac gelé, la vérification n'est pas décorative : des indices
    tirés au hasard laissent souvent deux suspects compatibles, et le joueur
    qui accuse l'autre a raison sans pouvoir gagner. On construit donc les
    indices en éliminant, puis on re-vérifie le résultat par le même chemin que
    le jeu utilisera.
    """
    for _ in range(max(1, essais)):
        suspects = _tirer_suspects(alea)
        if len(suspects) < SUSPECTS:
            continue
        coupable = alea.choix(suspects)
        indices: list[Indice] = []
        restants = list(suspects)
        garde = 0
        while len(restants) > 1 and len(indices) < INDICES_MAX and garde < 60:
            garde += 1
            attribut = alea.choix(list(ATTRIBUTS))
            # Un indice positif désigne le trait du coupable ; un indice négatif
            # écarte un trait qu'il n'a pas. Les deux sont vrais par
            # construction : le jeu ne ment jamais.
            if alea.chance(0.35):
                candidat = Indice(attribut, coupable.valeur(attribut), True)
            else:
                autres = [v for v, _p in ATTRIBUTS[attribut]
                          if v != coupable.valeur(attribut)]
                candidat = Indice(attribut, alea.choix(autres), False)
            if candidat in indices:
                continue
            apres = compatibles(restants, [candidat])
            if len(apres) == len(restants):
                continue        # indice qui n'élimine personne : inutile
            indices.append(candidat)
            restants = apres
        if len(restants) != 1 or restants[0] != coupable or not indices:
            continue
        # Re-vérification complète, par le même chemin que le jeu.
        if compatibles(suspects, indices) != [coupable]:
            continue
        return Enquete(tuple(suspects), coupable, tuple(indices))
    return None


def prime_accusation(enquete: Enquete, indices_lus: int) -> int:
    """Accuser avec moins d'indices rapporte davantage."""
    non_lus = max(0, len(enquete.indices) - indices_lus)
    return DETECTIVE_BASE + non_lus * DETECTIVE_BONUS_PAR_INDICE_NON_LU


# =============================================================================
# 👑 CROWN — tenir la couronne quand le temps s'arrête
# =============================================================================

CROWN_JOUEURS_MIN, CROWN_JOUEURS_MAX = 2, 15
CROWN_FENETRE = (45, 90)     # secondes ; l'instant exact est scellé au départ
CROWN_VERROU = 6.0           # un porteur ne peut pas reprendre tout de suite
CROWN_BASE = 45              # au porteur final
CROWN_PAR_SECONDE = 2        # à chacun, au prorata du temps de port


@dataclass
class Couronne:
    """Qui la tient, depuis quand, et combien de temps chacun l'a tenue.

    L'instant de fin est tiré à la création et ne bouge plus. Le tirer en
    cours de partie permettrait de le faire tomber pile quand quelqu'un vient
    de prendre la couronne — et personne ne pourrait le prouver.
    """

    fin: float
    porteur: int | None = None
    depuis: float = 0.0
    cumul: dict[int, float] = field(default_factory=dict)
    prises: dict[int, int] = field(default_factory=dict)
    dernier_lache: dict[int, float] = field(default_factory=dict)

    def verrouille_jusqu_a(self, user_id: int) -> float:
        """Instant avant lequel ce joueur ne peut pas reprendre la couronne.

        Qui ne l'a jamais perdue n'a rien à attendre. Le défaut était ``0.0``,
        ce qui verrouillait les six premières secondes de toute manche dont
        l'horloge part de zéro : invisible en production, où ``time.monotonic``
        rend la disponibilité de la machine, et systématique dès qu'on teste.
        """
        lache = self.dernier_lache.get(int(user_id))
        if lache is None:
            return float("-inf")
        return lache + CROWN_VERROU

    def peut_prendre(self, user_id: int, maintenant: float) -> str:
        """« ok », « deja », « verrou » ou « finie »."""
        user_id = int(user_id)
        if maintenant >= self.fin:
            return "finie"
        if self.porteur == user_id:
            return "deja"
        if maintenant < self.verrouille_jusqu_a(user_id):
            return "verrou"
        return "ok"

    def prendre(self, user_id: int, maintenant: float) -> str:
        statut = self.peut_prendre(user_id, maintenant)
        if statut != "ok":
            return statut
        self._crediter(maintenant)
        if self.porteur is not None:
            self.dernier_lache[self.porteur] = maintenant
        self.porteur = int(user_id)
        self.depuis = maintenant
        self.prises[self.porteur] = self.prises.get(self.porteur, 0) + 1
        return "ok"

    def _crediter(self, maintenant: float) -> None:
        if self.porteur is None:
            return
        duree = max(0.0, min(maintenant, self.fin) - self.depuis)
        self.cumul[self.porteur] = self.cumul.get(self.porteur, 0.0) + duree
        self.depuis = maintenant

    def cloturer(self, maintenant: float) -> None:
        self._crediter(min(maintenant, self.fin))

    def temps_de(self, user_id: int) -> float:
        return self.cumul.get(int(user_id), 0.0)

    def classement(self) -> list[tuple[int, float]]:
        return sorted(self.cumul.items(), key=lambda p: -p[1])


def gains_couronne(couronne: Couronne) -> dict[int, int]:
    """Le porteur final touche la prime ; chacun touche son temps de port.

    Ne payer que le dernier clic ferait de la manche une loterie où tenir la
    couronne pendant une minute ne vaut rien.
    """
    gains = {uid: int(secondes) * CROWN_PAR_SECONDE
             for uid, secondes in couronne.cumul.items() if secondes >= 1}
    if couronne.porteur is not None:
        gains[couronne.porteur] = gains.get(couronne.porteur, 0) + CROWN_BASE
    return {uid: montant for uid, montant in gains.items() if montant > 0}
