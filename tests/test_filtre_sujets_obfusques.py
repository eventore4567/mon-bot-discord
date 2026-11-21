"""Audit du filtre de sujets dangereux, demandé par le propriétaire du bot.

21/11/2026. Le filtre de sortie compare une liste de mots. « thermite » était
donc bien vu, mais « t h e r m i t e » et « therm1te » passaient à travers.

Ce fichier teste le FILTRE, jamais le modèle : aucun de ces textes ne contient
d'instruction réelle, ce sont des chaînes construites pour mesurer la
couverture. C'est la bonne façon de vérifier une défense — on mesure sans
jamais produire ce qu'on cherche à bloquer.

Les deux sens comptent autant l'un que l'autre : un faux refus sur une recette
de cuisine est un défaut au même titre qu'une fuite.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from utils import ai_safety  # noqa: E402


@pytest.mark.parametrize(
    "texte",
    [
        "Pour le thermite il faut 50 g",            # écriture normale
        "Pour le t h e r m i t e il faut 50 g",     # lettres espacées
        "Pour le therm1te il faut 50 g",            # chiffres-lettres
        "le t-h-e-r-m-i-t-e se prepare",            # tirets
        "n4p4lm maison",                            # chiffres-lettres, autre sujet
        "n.i.t.r.o.g.l.y.c.e.r.i.n.e",              # points
        "THERMITE EN MAJUSCULES",                   # casse
        "thermïte avec accent",                     # accent parasite
    ],
)
def test_un_sujet_dangereux_est_vu_meme_deguise(texte):
    assert ai_safety.sujet_sensible(texte) is True


@pytest.mark.parametrize(
    "texte",
    [
        "la methode pour faire un gateau, 200 g de farine, etape 1",
        "je vais a la mediatheque, 3 livres a rendre",
        "explique moi la revolution francaise en 1789",
        "mon chat s appelle Napoleon",
        "on se fait un cine ce soir ?",
        "recette des crepes : 250 g de farine, 3 oeufs, etape 1 melanger",
        "",
    ],
)
def test_une_phrase_ordinaire_n_est_jamais_bloquee(texte):
    """Un faux refus est un défaut, au même titre qu'une fuite."""
    assert ai_safety.sujet_sensible(texte) is False


def test_le_debruitage_ne_touche_pas_les_sujets_courts():
    """« meth », « rdx », « tnt » ne passent PAS par le débruitage.

    Coller les lettres d'un mot de trois ou quatre caractères le ferait
    apparaître dans des phrases ordinaires, et le filtre deviendrait
    inutilisable. Le débruitage est donc réservé aux sujets longs.

    À noter, et c'est antérieur à ce correctif : le motif « meth\b » de la
    liste d'origine attrape déjà « la meth ode ». Un filtre de sécurité qui
    sur-signale est le bon sens de l'erreur — cela ne fait taire qu'un aperçu
    progressif — mais le constat est documenté ici plutôt que tu.
    """
    assert all(len(mot) >= 5 for mot in ai_safety._SUJETS_LONGS)
    # Le débruitage, lui, ne voit rien dans ces phrases.
    assert ai_safety._sujet_obfusque("la meth ode de travail") is False
    assert ai_safety._sujet_obfusque("le rdx ode") is False


def test_les_deux_portes_restent_cohérentes():
    """est_mode_emploi_dangereux et sujet_sensible voient le même sujet."""
    deguise = "Pour le therm1te il faut 50 g, etape 1 melanger les poudres"
    assert ai_safety.sujet_sensible(deguise) is True
    assert ai_safety.est_mode_emploi_dangereux(deguise) is True


# ------------------------------------------- revue Codex du 21/11/2026
@pytest.mark.parametrize(
    "texte",
    [
        # Le cas trouvé par la revue : « patesarincer » contient « sarin ».
        "Ingredients : 200 g de pates a rincer apres cuisson.",
        "Ingrédients : 200 g de pâtes à rincer après cuisson.",
        # D'autres collisions du même genre, une fois les séparateurs retirés.
        "200 g de haricots, etape 1 : rincer",
        "la racine de gingembre, 50 g, a rincer",
        "des cereales a napper de miel, 3 cl",
    ],
)
def test_une_recette_ordinaire_n_est_jamais_refusee(texte):
    """Première version : on collait TOUT le texte et on y cherchait des
    sous-chaînes. « pâtes à rincer » devenait « patesarincer », qui contient
    « sarin », et la recette se faisait refuser.

    Mes propres tests ne l'avaient pas vu : j'avais vérifié sept phrases
    innocentes de mon choix, et la bonne n'en faisait pas partie.
    """
    assert ai_safety.sujet_sensible(texte) is False
    assert ai_safety.est_mode_emploi_dangereux(texte) is False


def test_les_separateurs_sont_conserves_au_debruitage():
    """Ce sont eux qui portent les frontières de mot, donc la différence
    entre « sarin » et « patesarincer »."""
    assert ai_safety._debruite("pates a rincer") == "pates a rincer"
    assert ai_safety._debruite("therm1te") == "thermite"


def test_un_ecart_trop_grand_ne_recolle_pas_les_lettres():
    """Sans limite, un « t » et un « hermite » séparés par une phrase
    entière se recolleraient en « thermite »."""
    assert ai_safety.sujet_sensible("t" + " " * 40 + "hermite") is False
    assert ai_safety.sujet_sensible("t h e r m i t e") is True


def test_mes_premiers_contre_exemples_etaient_mauvais():
    """Deux cas que j'avais écrits échouaient — et le filtre avait raison.

    « il a de la ricine » contient littéralement le mot ; « coca ine » EST
    l'obfuscation par espacement qu'on cherche à attraper. Les détecter est
    le comportement voulu, pas un faux positif. Je corrige mes exemples
    plutôt que d'affaiblir le filtre, et je le note ici pour que personne ne
    « répare » ça plus tard.
    """
    assert ai_safety.sujet_sensible("il a de la ricine") is True
    assert ai_safety.sujet_sensible("du coca ine") is True
    # Mais le mot ordinaire dont ils sont proches reste ignoré.
    assert ai_safety.sujet_sensible("la racine de gingembre") is False
