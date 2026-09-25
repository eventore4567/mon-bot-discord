"""Lac gelé : génération sous solveur.

Près de six grilles sur dix tirées au hasard n'ont aucune solution. Sans le
parcours en largeur exécuté AVANT l'envoi, la majorité des manches seraient
injouables sans que personne ne s'en aperçoive — le joueur croirait simplement
être mauvais.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from utils import ice_puzzle as ice
from utils.pve_engine import AleaPseudo


# =============================================================================
# Glissade
# =============================================================================

def test_le_pingouin_glisse_jusqu_au_bord():
    assert ice.glisser((2, 2), "gauche", frozenset(), 6) == (0, 2)
    assert ice.glisser((2, 2), "droite", frozenset(), 6) == (5, 2)
    assert ice.glisser((2, 2), "haut", frozenset(), 6) == (2, 0)
    assert ice.glisser((2, 2), "bas", frozenset(), 6) == (2, 5)


def test_il_s_arrete_avant_le_rocher_jamais_dessus():
    rochers = frozenset({(0, 2)})
    assert ice.glisser((4, 2), "gauche", rochers, 6) == (1, 2)


def test_il_ne_sort_jamais_de_la_grille():
    """Tester l'obstacle après avoir bougé le ferait sortir d'une case au bord."""
    for direction in ice.DIRECTIONS:
        for x in range(6):
            for y in range(6):
                arrivee = ice.glisser((x, y), direction, frozenset(), 6)
                assert ice.dans_la_grille(arrivee, 6), (x, y, direction, arrivee)


def test_une_direction_bloquee_ne_bouge_pas():
    rochers = frozenset({(3, 2)})
    assert ice.glisser((2, 2), "droite", rochers, 6) == (2, 2)


def test_coince_entre_quatre_rochers_il_ne_bouge_dans_aucune_direction():
    rochers = frozenset({(1, 2), (3, 2), (2, 1), (2, 3)})
    for direction in ice.DIRECTIONS:
        assert ice.glisser((2, 2), direction, rochers, 6) == (2, 2)


# =============================================================================
# Solveur
# =============================================================================

def test_le_solveur_trouve_un_chemin_evident():
    # Un rocher en (5,0) arrête le pingouin pile sur (4,0).
    chemin = ice.resoudre((0, 0), (4, 0), frozenset({(5, 0)}), 6)
    assert chemin == ("droite",)


def test_le_solveur_rend_le_chemin_le_plus_court():
    for graine in range(60):
        niveau = ice.generer(AleaPseudo(graine))
        assert niveau is not None
        direct = ice.resoudre(niveau.depart, niveau.trou, niveau.rochers, niveau.taille)
        assert len(direct) == len(niveau.solution)


def test_le_solveur_conclut_sur_une_grille_insoluble():
    """Il doit répondre None, pas boucler : chaque case n'est visitée qu'une fois."""
    # Le trou est enfermé par des rochers : aucune glissade ne peut s'y arrêter.
    rochers = frozenset({(2, 1), (2, 3), (1, 2), (3, 2)})
    assert ice.resoudre((0, 0), (2, 2), rochers, 6) is None


def test_depart_confondu_avec_le_trou_donne_un_chemin_vide():
    assert ice.resoudre((1, 1), (1, 1), frozenset(), 6) == ()


# =============================================================================
# Génération de masse
# =============================================================================

@pytest.mark.parametrize("lot", range(6))
def test_mille_niveaux_par_lot_sont_tous_reellement_solubles(lot):
    """Six mille niveaux au total. 100 % des grilles envoyables ont une solution,
    et cette solution, rejouée coup par coup, atteint bien le trou."""
    for graine in range(lot * 1000, lot * 1000 + 1000):
        niveau = ice.generer(AleaPseudo(graine))
        assert niveau is not None, f"génération en échec à la graine {graine}"
        position = niveau.depart
        for direction in niveau.solution:
            suivante = ice.glisser(position, direction, niveau.rochers, niveau.taille)
            assert ice.dans_la_grille(suivante, niveau.taille), "sortie de grille"
            assert suivante not in niveau.rochers, "arrêt dans un rocher"
            assert suivante != position, "glissade nulle dans la solution"
            position = suivante
        assert position == niveau.trou, f"la solution n'atteint pas le trou ({graine})"


def test_les_niveaux_respectent_leurs_bornes():
    for graine in range(500):
        niveau = ice.generer(AleaPseudo(graine))
        assert ice.LONGUEUR_MIN <= len(niveau.solution) <= ice.LONGUEUR_MAX
        assert ice.ROCHERS[0] <= len(niveau.rochers) <= ice.ROCHERS[1]
        assert niveau.depart not in niveau.rochers
        assert niveau.trou not in niveau.rochers
        assert niveau.depart != niveau.trou
        assert ice.dans_la_grille(niveau.depart, niveau.taille)
        assert ice.dans_la_grille(niveau.trou, niveau.taille)


def test_le_joueur_a_une_marge_sur_la_solution_optimale():
    """Exiger le chemin optimal ferait perdre un joueur qui a compris le niveau."""
    niveau = ice.generer(AleaPseudo(3))
    assert niveau.coups_max == len(niveau.solution) + ice.COUPS_ACCORDES
    assert ice.COUPS_ACCORDES >= 1


def test_la_generation_rend_la_main_au_lieu_de_boucler():
    """Bornes impossibles : il faut répondre None, pas tourner indéfiniment."""
    assert ice.generer(AleaPseudo(1), longueur_min=900, longueur_max=901, essais=25) is None


def test_le_solveur_n_est_pas_decoratif():
    """Mesure ce que coûterait son absence : la part de grilles insolubles."""
    insolubles = 0
    total = 600
    for graine in range(50_000, 50_000 + total):
        alea = AleaPseudo(graine)
        rochers: set[tuple[int, int]] = set()
        while len(rochers) < alea.entier(*ice.ROCHERS):
            rochers.add((alea.entier(0, ice.TAILLE - 1), alea.entier(0, ice.TAILLE - 1)))
        libres = [(x, y) for y in range(ice.TAILLE) for x in range(ice.TAILLE)
                  if (x, y) not in rochers]
        depart = alea.choix(libres)
        trou = alea.choix([c for c in libres if c != depart])
        if ice.resoudre(depart, trou, frozenset(rochers), ice.TAILLE) is None:
            insolubles += 1
    part = 100 * insolubles / total
    assert part > 30, (
        f"seulement {part:.1f} % de grilles brutes insolubles — vérifier la "
        "difficulté, le solveur est censé écarter une grille sur deux")


# =============================================================================
# Rendu
# =============================================================================

def test_la_grille_dessinee_a_la_bonne_forme():
    """On compte les pictogrammes, pas les caractères.

    ``len()`` compte des points de code : 🕳️ en vaut deux (le sélecteur de
    variante U+FE0F), 🟦 un seul. Une rangée contenant le trou serait donc plus
    « longue » que les autres alors qu'elle affiche bien six cases.
    """
    niveau = ice.generer(AleaPseudo(9))
    lignes = ice.dessiner(niveau, niveau.depart).split("\n")
    assert len(lignes) == niveau.taille
    cases = (ice.GLACE, ice.ROCHER, ice.PINGOUIN, ice.TROU)
    for ligne in lignes:
        assert sum(ligne.count(c) for c in cases) == niveau.taille, repr(ligne)
        assert not ligne.replace("".join(c * ligne.count(c) for c in cases), "").strip("".join(cases))


def test_le_pingouin_passe_devant_le_trou():
    """Arrivé au but, le joueur doit voir son pingouin, pas la case d'arrivée."""
    niveau = ice.generer(AleaPseudo(9))
    dessin = ice.dessiner(niveau, niveau.trou)
    assert ice.TROU not in dessin
    assert dessin.count(ice.PINGOUIN) == 1


def test_chaque_direction_a_une_fleche():
    assert set(ice.FLECHES) == set(ice.DIRECTIONS)
    assert len(set(ice.FLECHES.values())) == 4, "deux directions ne peuvent pas partager une flèche"
