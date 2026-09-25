"""Génération et résolution des niveaux de ``+ice``.

Un lac gelé : le pingouin glisse jusqu'à heurter un rocher ou le bord, jamais
d'une case. Il faut s'arrêter EXACTEMENT sur le trou, ce qui rend la majorité
des grilles tirées au hasard insolubles — et c'est précisément pourquoi le
solveur n'est pas un luxe. Aucune grille n'est envoyée à un joueur sans qu'un
parcours en largeur ait d'abord trouvé le chemin complet.

Rien d'aléatoire n'est lu depuis Discord et rien n'est recalculé après le
premier clic : le niveau est scellé à la génération, solution comprise.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

# (dx, dy) — y croît vers le bas, comme les lignes affichées.
DIRECTIONS: dict[str, tuple[int, int]] = {
    "haut": (0, -1),
    "bas": (0, 1),
    "gauche": (-1, 0),
    "droite": (1, 0),
}
FLECHES = {"haut": "⬆️", "bas": "⬇️", "gauche": "⬅️", "droite": "➡️"}

GLACE, ROCHER, PINGOUIN, TROU = "🟦", "🪨", "🐧", "🕳️"

TAILLE = 6
ROCHERS = (7, 11)          # bornes du nombre de rochers posés
LONGUEUR_MIN = 4           # en deçà, le niveau se résout sans réfléchir
LONGUEUR_MAX = 14
COUPS_ACCORDES = 3         # marge au-dessus de la solution optimale
ESSAIS_GENERATION = 400


@dataclass(frozen=True)
class Niveau:
    taille: int
    rochers: frozenset[tuple[int, int]]
    depart: tuple[int, int]
    trou: tuple[int, int]
    solution: tuple[str, ...]

    @property
    def coups_max(self) -> int:
        return len(self.solution) + COUPS_ACCORDES


def dans_la_grille(case: tuple[int, int], taille: int) -> bool:
    x, y = case
    return 0 <= x < taille and 0 <= y < taille


def glisser(depart: tuple[int, int], direction: str, rochers, taille: int) -> tuple[int, int]:
    """Case d'arrêt après une glissade. Ne sort jamais de la grille.

    On avance case par case et on s'arrête AVANT l'obstacle : tester l'obstacle
    après avoir bougé ferait sortir le pingouin du lac d'une case sur les bords.
    """
    dx, dy = DIRECTIONS[direction]
    x, y = depart
    while True:
        suivant = (x + dx, y + dy)
        if not dans_la_grille(suivant, taille) or suivant in rochers:
            return (x, y)
        x, y = suivant


def resoudre(depart, trou, rochers, taille: int) -> tuple[str, ...] | None:
    """Chemin le plus court, en parcours en largeur. ``None`` si insoluble.

    Le graphe est fini (au plus ``taille²`` cases) et chaque case n'est visitée
    qu'une fois : la recherche se termine toujours, y compris sur une grille
    sans solution — il n'y a pas de boucle infinie possible ici.
    """
    if depart == trou:
        return ()
    vus = {depart}
    file: deque[tuple[tuple[int, int], tuple[str, ...]]] = deque([(depart, ())])
    while file:
        case, chemin = file.popleft()
        for direction in DIRECTIONS:
            arrivee = glisser(case, direction, rochers, taille)
            if arrivee == case or arrivee in vus:
                continue        # glissade nulle, ou case déjà atteinte plus tôt
            if arrivee == trou:
                return chemin + (direction,)
            vus.add(arrivee)
            file.append((arrivee, chemin + (direction,)))
    return None


def _cases_libres(taille: int, rochers) -> list[tuple[int, int]]:
    return [(x, y) for y in range(taille) for x in range(taille) if (x, y) not in rochers]


def generer(alea, *, taille: int = TAILLE, longueur_min: int = LONGUEUR_MIN,
            longueur_max: int = LONGUEUR_MAX, essais: int = ESSAIS_GENERATION) -> Niveau | None:
    """Tire une grille, la résout, et ne la retourne que si elle est jouable.

    Retourne ``None`` après ``essais`` tentatives infructueuses plutôt que de
    boucler : l'appelant doit pouvoir répondre au joueur même le jour où les
    bornes demandées sont impossibles à satisfaire.
    """
    for _ in range(max(1, essais)):
        nombre = alea.entier(*ROCHERS)
        rochers: set[tuple[int, int]] = set()
        while len(rochers) < nombre:
            rochers.add((alea.entier(0, taille - 1), alea.entier(0, taille - 1)))
        libres = _cases_libres(taille, rochers)
        if len(libres) < 2:
            continue
        depart = alea.choix(libres)
        trou = alea.choix([c for c in libres if c != depart])
        solution = resoudre(depart, trou, rochers, taille)
        if solution is None or not longueur_min <= len(solution) <= longueur_max:
            continue
        return Niveau(taille, frozenset(rochers), depart, trou, tuple(solution))
    return None


def dessiner(niveau: Niveau, position: tuple[int, int]) -> str:
    """Grille rendue en émojis, une ligne par rangée.

    Le pingouin passe devant le trou : sinon, arrivé au but, le joueur verrait
    la case de destination et plus son propre personnage.
    """
    lignes = []
    for y in range(niveau.taille):
        ligne = []
        for x in range(niveau.taille):
            case = (x, y)
            if case == position:
                ligne.append(PINGOUIN)
            elif case in niveau.rochers:
                ligne.append(ROCHER)
            elif case == niveau.trou:
                ligne.append(TROU)
            else:
                ligne.append(GLACE)
        lignes.append("".join(ligne))
    return "\n".join(lignes)
