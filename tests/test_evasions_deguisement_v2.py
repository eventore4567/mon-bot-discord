"""Les déguisements que le filtre d'insultes laissait passer.

Mesuré avec tools/security_bypass_sweep.py le 2026-10-14. Le balayage
annonçait 407/407 — mais un corpus épuisé ne prouve pas qu'un filtre est
solide, seulement qu'on a cessé de chercher. Huit familles de déguisement
courantes manquaient. Une fois ajoutées : 114 évasions sur 727.

Deux fuites, corrigées dans utils/moderation_dataset :

- la découpe par balisage Discord (« co||nnard », « co**nnard** ») : la
  ponctuation devenant un espace, le mot arrivait en deux tokens que rien
  ne recollait, le recollage ne traitant que les suites de caractères
  isolés (« c o n ») — 76 évasions ;
- les lettres étirées (« coonnaard ») — 38 évasions.

Après correction : 11 évasions sur 727, et toujours 0 faux positif. Les 11
restantes sont des termes qui contiennent eux-mêmes une lettre doublée, que
le compactage détruit aussi ; les rattraper demanderait de compacter aussi
l'index des termes, ce qui élargirait la surface de faux positifs pour
1,5 % d'attaques. Mesure faite, le marché n'en vaut pas la peine.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from utils.moderation_dataset import (
    MultilingualModerationDataset,
    _compacter_repetitions,
    normalize_message,
)

_DATASET = MultilingualModerationDataset()


def _terme_temoin() -> str:
    """Un terme ASCII du dataset, sans lettre doublée (cas que l'on corrige)."""
    return sorted(
        t for t in _DATASET._terms
        if t.isascii() and 5 <= len(t) <= 9 and _compacter_repetitions(t) == t
    )[0]


def test_le_compactage_ne_garde_qu_une_lettre_par_serie():
    assert _compacter_repetitions("aaaanduu") == "andu"
    assert _compacter_repetitions("coool") == "col"
    assert _compacter_repetitions("abc") == "abc"


@pytest.mark.parametrize("marqueur", ["||", "**", "__", "~~", "`"])
def test_le_balisage_discord_ne_coupe_plus_les_mots(marqueur):
    """Le lecteur voit un seul mot : le filtre doit voir la même chose."""
    terme = _terme_temoin()
    coupe = terme[:2] + marqueur + terme[2:]
    assert _DATASET.match(f"tu es un {coupe} franchement") is not None, (
        f"« {coupe} » passe encore"
    )


@pytest.mark.parametrize("etirer", [
    lambda t: "".join(c * 2 if c in "aeiou" else c for c in t),
    lambda t: "".join(c * 3 if c == t[0] else c for c in t),
])
def test_les_lettres_etirees_ne_passent_plus(etirer):
    terme = _terme_temoin()
    etire = etirer(terme)
    assert etire != terme
    assert _DATASET.match(f"tu es un {etire} franchement") is not None, (
        f"« {etire} » passe encore"
    )


@pytest.mark.parametrize("phrase", [
    "j'ai une bonne connexion internet",
    "appelle moi quand tu veux",
    "cette collection est magnifique",
    "mille mercis pour votre aide",
    "ennuyeux mais nécessaire",
    "la grammaire est correcte",
    "parfaitement d'accord avec toi",
    "toutes les commandes fonctionnent",
    "allo tout le monde ça va",
    "nous avons une bonne nouvelle",
    "c'est trop cool merci beaucoup",
    "le programme commence à vingt heures",
])
def test_le_francais_courant_n_est_pas_sanctionne(phrase):
    """La contrepartie du compactage, et la seule qui compte vraiment.

    « bonne » produit « bone » comme candidat supplémentaire. Un serveur qui
    supprime les messages normaux de ses membres est pire qu'un serveur sans
    filtre : les admins coupent la protection, et il n'en reste rien.
    """
    assert _DATASET.match(phrase) is None, f"faux positif sur {phrase!r}"


def test_le_compactage_est_un_candidat_pas_un_remplacement():
    """« bonne » doit rester « bonne » ; on ajoute une forme, on n'en retire pas."""
    from utils.moderation_dataset import _tokens_candidats

    candidats = _tokens_candidats(("bonne",))
    assert "bonne" in candidats
    assert "bone" in candidats


def test_le_balisage_est_retire_avant_la_passe_de_ponctuation():
    """Sinon les marqueurs deviendraient des espaces et couperaient le mot."""
    assert "abcdef" in normalize_message("abc||def")
    assert "abcdef" in normalize_message("abc**def**")
