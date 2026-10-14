"""Des phrases françaises ordinaires étaient supprimées.

Mesuré le 2026-10-14 sur 151 mots français courants : trois d'entre eux
— « balle », « folle », « pelle » — déclenchaient le filtre multilingue
avec une confiance de 0,70, soit au-dessus du seuil de suppression de
cogs/automod. « Il a attrapé la balle au vol » disparaissait.

Les retirer du dataset laisserait passer « tu es une folle ». Ils exigent
donc une attribution explicite : quelqu'un doit ÊTRE traité de ce mot.
Un simple possessif ne suffit pas, sinon « la balle est dans ton camp »
tomberait aussi.

Cas particulier de « pelle » : ce n'est pas « pelle » qui est dans le
dataset mais « pele ». C'est donc le compactage des lettres étirées,
ajouté le même jour pour fermer 38 évasions, qui l'avait rendu
détectable — une régression de mon propre correctif, trouvée en scannant
les 12 760 mots du dépôt.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from utils.moderation_dataset import MultilingualModerationDataset

_DATASET = MultilingualModerationDataset()


@pytest.mark.parametrize("phrase", [
    "il a attrapé la balle au vol",
    "cette idée est folle mais géniale",
    "je mets une pelle dans le coffre",
    "j'ai acheté une pelle au magasin",
    "une folle journée nous attend",
    "ta pelle est dans le jardin",
    "la balle est dans ton camp",
    "il est tout pâle ce matin",
    "j'ai mal à la tête depuis hier",
])
def test_le_francais_ordinaire_n_est_pas_supprime(phrase):
    assert _DATASET.match(phrase) is None, f"faux positif sur {phrase!r}"


@pytest.mark.parametrize("phrase", [
    "tu es une folle",
    "t'es qu'une pelle",
    "tu n'es qu'une balle",
    "t'as vraiment une tête de pelle",
    "espèce de folle",
    "sale folle",
])
def test_l_insulte_adressee_reste_vue(phrase):
    assert _DATASET.match(phrase) is not None, f"insulte manquée : {phrase!r}"


def test_la_contraction_t_apostrophe_compte_comme_une_cible():
    """La normalisation casse l'apostrophe : « t'es » devient « t es ».

    Sans cela, la forme la plus courante en tchat français n'était pas
    vue comme adressée alors que « tu es » l'était.
    """
    from utils.moderation_dataset import _context_confidence, normalize_message

    _, cible_contractee, _ = _context_confidence(normalize_message("t'es qu'une folle"), "mot")
    _, cible_pleine, _ = _context_confidence(normalize_message("tu es une folle"), "mot")
    assert cible_contractee is True
    assert cible_pleine is True


def test_un_possessif_seul_ne_vaut_pas_attribution():
    """« la balle est dans ton camp » contient « ton » et reste une expression."""
    from utils.moderation_dataset import _attribue_a_quelquun, normalize_message

    assert not _attribue_a_quelquun(normalize_message("la balle est dans ton camp"))
    assert _attribue_a_quelquun(normalize_message("tu es une folle"))


def test_indexer_la_forme_compactee_des_termes_reste_refuse():
    """Décision mesurée, pas supposée.

    Indexer aussi la forme compactée des TERMES fermerait les 11 évasions
    restantes. Scan sur les 12 760 mots du dépôt : cela rendrait « tête »
    et « pâle » détectables. « Tête » est l'un des mots les plus courants
    du français — le marché n'en vaut pas la peine.
    """
    from utils.moderation_dataset import _compacter_repetitions

    termes = set(_DATASET._terms)
    nouvelles = {_compacter_repetitions(t) for t in termes} - termes
    assert "tete" in nouvelles, (
        "si « tete » n'est plus produit, la décision mérite d'être réévaluée"
    )
    assert _DATASET.match("j'ai mal à la tête") is None
