"""La barre de progression bouge sans coûter une requête par seconde.

Faire avancer une barre en rééditant le message coûte un appel Discord par
seconde ET par panneau. Un curseur animé bouge tout seul, côté client,
indéfiniment, pour un seul envoi.

Ces tests figent les deux garanties qui comptent : la barre reste lisible
quand les icônes ne sont pas disponibles, et elle ne s'anime que quand
quelque chose avance réellement.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from utils import design_system as ds
from utils import sentrix_emojis as se


@pytest.fixture(autouse=True)
def _sans_icones():
    """Chaque test part de l'état « icônes pas encore téléversées »."""
    se.reinitialiser()
    yield
    se.reinitialiser()


@pytest.fixture
def avec_icones():
    se.amorcer({
        nom: f"<:{nom}:41000000000000{i:04d}>"
        for i, nom in enumerate(se.noms_disponibles())
    })
    yield


def _corps(rendu: str) -> str:
    """La barre sans son pourcentage."""
    return rendu.split("  ")[0]


# =============================================================================
# Sans icônes : rien ne doit dépasser
# =============================================================================

def test_sans_icones_la_barre_ne_contient_que_ses_blocs():
    """``emoji("loading")`` rend « … » quand l'icône manque — juste dans une
    phrase, faux dans une barre : le curseur afficherait des points de
    suspension au milieu des blocs."""
    for courant in range(0, 11):
        corps = _corps(ds.barre_progression(courant, 10))
        intrus = set(corps) - {ds.PLEIN, ds.VIDE}
        assert intrus == set(), f"{courant}/10 : caractères parasites {intrus}"


def test_sans_icones_la_longueur_est_constante():
    for courant in range(0, 11):
        assert len(_corps(ds.barre_progression(courant, 10))) == 10


# =============================================================================
# Avec icônes : le curseur dit l'état
# =============================================================================

def test_le_curseur_anime_la_frontiere(avec_icones):
    rendu = ds.barre_progression(5, 10)
    assert "sentrix_loading" in rendu
    avant, apres = rendu.split("<:sentrix_loading:", 1)
    assert avant.count(ds.PLEIN) == 4, "le curseur n'est pas à la frontière"
    assert apres.split(">", 1)[1].startswith(ds.VIDE)


def test_une_barre_vide_ne_sanime_pas(avec_icones):
    """Rien n'avance : animer laisserait croire le contraire."""
    assert "sentrix_" not in ds.barre_progression(0, 10)


def test_une_barre_terminee_montre_une_coche_et_pas_un_chargement(avec_icones):
    """Il n'y a plus rien à attendre : un curseur de chargement à 100 % est un
    mensonge."""
    rendu = ds.barre_progression(10, 10)
    assert "sentrix_success" in rendu
    assert "sentrix_loading" not in rendu


def test_une_jauge_figee_ne_sanime_pas(avec_icones):
    """Un score de configuration ou un niveau MESURE, il n'avance pas. Animer
    une valeur figée laisserait croire qu'elle bouge."""
    assert "sentrix_" not in ds.barre_progression(5, 10, en_cours=False)


# =============================================================================
# Les bornes
# =============================================================================

@pytest.mark.parametrize("courant,maximum,attendu", [
    (0, 0, 0), (-5, 10, 0), (15, 10, 100), (5, 10, 50), (1, 3, 33),
])
def test_le_pourcentage_reste_dans_les_bornes(courant, maximum, attendu):
    assert ds.barre_progression(courant, maximum).endswith(f"{attendu} %")


def test_un_maximum_nul_ne_divise_pas_par_zero():
    assert _corps(ds.barre_progression(5, 0)) == ds.VIDE * 10


@pytest.mark.parametrize("longueur,attendue", [(1, 4), (4, 4), (10, 10), (99, 30)])
def test_la_longueur_est_bornee(longueur, attendue):
    """Une barre de 99 cases déborde sur mobile ; une barre de 1 ne dit rien."""
    assert len(_corps(ds.barre_progression(1, 2, longueur=longueur))) == attendue


# =============================================================================
# Compatibilité des appelants historiques
# =============================================================================

def test_les_appelants_historiques_gagnent_le_curseur(avec_icones):
    """``progress_bar`` est appelée à plusieurs endroits : ils profitent du
    rendu premium sans rien changer."""
    assert "sentrix_loading" in ds.progress_bar(4, 10)


def test_des_glyphes_personnalises_restent_respectes(avec_icones):
    """Un appelant qui choisit ses caractères a une raison : un curseur
    SentriX au milieu jurerait avec."""
    rendu = ds.progress_bar(4, 10, filled="=", empty="-")
    assert "sentrix_" not in rendu
    assert _corps(rendu) == "====------"
