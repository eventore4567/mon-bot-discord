"""« Si il rep la même chose a tout le monde c'est null » (20/11/2026).

Deux « t'es là ? » de suite recevaient la même ouverture. Deux causes
distinctes, et il fallait traiter les deux :

1. Un fast-path local associait à chaque phrase courte UNE réponse unique,
   au mot près. Tout le monde lisait exactement la même chose, à chaque fois.
2. Sur le vrai pipeline, c'est le modèle qui répond, et rien ne lui demandait
   de varier — il retombait donc sur ses tournures par défaut.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from cogs import natural_music_intent_guard as garde  # noqa: E402
from utils import ai_conversation  # noqa: E402


@pytest.mark.parametrize("phrase", ["slt", "tes la ?", "cv", "yo", "coucou", "ca va"])
def test_une_phrase_courte_a_plusieurs_reponses_possibles(phrase):
    """Quarante tirages doivent produire plus d'une formulation."""
    obtenues = {garde._casual_reply(phrase) for _ in range(40)}
    assert None not in obtenues, f"« {phrase} » doit rester reconnue"
    assert len(obtenues) >= 2, f"« {phrase} » répond toujours « {obtenues} »"


def test_chaque_entree_de_la_table_propose_au_moins_deux_variantes():
    """Le piège serait d'en varier trois et d'oublier les autres."""
    figees = {
        cle: variantes for cle, variantes in garde._CASUAL_REPLIES.items()
        if len(variantes) < 2
    }
    assert not figees, f"ces entrées n'ont qu'une seule réponse : {sorted(figees)}"


def test_les_variantes_sont_toutes_distinctes():
    for cle, variantes in garde._CASUAL_REPLIES.items():
        assert len(set(variantes)) == len(variantes), f"doublon dans « {cle} »"


def test_les_variantes_restent_des_phrases_courtes():
    """Un small-talk reste un small-talk : pas de pavé dans le fast-path."""
    for cle, variantes in garde._CASUAL_REPLIES.items():
        for variante in variantes:
            assert variante.strip(), f"réponse vide dans « {cle} »"
            assert len(variante) <= 60, f"« {variante} » est trop longue pour un small-talk"


def test_une_phrase_inconnue_part_toujours_vers_l_ia():
    """Le fast-path ne doit pas se mettre à répondre à tout."""
    assert garde._casual_reply("explique moi la revolution francaise") is None
    assert garde._casual_reply("cv veut dire quoi ?") is None


def test_le_modele_recoit_la_consigne_de_varier():
    """Le fast-path ne couvre que 17 phrases ; le reste dépend du modèle."""
    consigne = ai_conversation.CONSIGNE_CONVERSATION
    assert "VARIE TES FORMULATIONS" in consigne
    assert "deux fois" in consigne
    assert "Oui" in consigne and "Carrément" in consigne, (
        "les ouvertures réellement observées doivent être nommées"
    )
