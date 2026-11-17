"""Le streaming arrive-t-il vraiment jusqu'à OpenAI ? (17/11/2026)

La première livraison du streaming a été branchée dans Ai.send_sentrix_reply.
Elle était correcte, testée, et totalement inerte : bot_experience_v5 REMPLACE
cette méthode, donc la production a continué à attendre la dernière lettre.
Les logs le disaient — « Reponse OpenAI terminee en 1482ms » et jamais une
seule ligne « Flux IA ». Aucun test ne regardait le chemin réel.

Ces tests regardent le chemin réel : on_delta doit traverser les signatures
des modules qui remplacent _prepare_and_generate, et ne JAMAIS être passé à
une signature qui ne le déclare pas (ce qui a déjà cassé tout le listener
avec image_urls).
"""
from __future__ import annotations

import inspect

import pytest

from cogs import bot_experience_v5


def test_les_trois_implementations_acceptent_on_delta():
    """Les trois signatures réellement installées en production."""
    from cogs import ai, community_v34, v17_ai_economy_games

    source_v34 = inspect.getsource(community_v34)
    assert "on_delta=None) -> dict:" in source_v34, "fast_prepare doit accepter on_delta"
    assert "on_delta=on_delta," in source_v34, "fast_prepare doit le transmettre"

    source_v17 = inspect.getsource(v17_ai_economy_games)
    assert "on_delta=None) -> dict:" in source_v17
    assert "on_delta=on_delta," in source_v17

    parametres = inspect.signature(ai.Ai._prepare_and_generate).parameters
    assert "on_delta" in parametres
    assert "on_delta=on_delta," in inspect.getsource(ai.Ai._prepare_and_generate)


def test_le_pipeline_reel_branche_l_apercu():
    """C'est CE pipeline qui répond à une mention, pas celui du Cog IA."""
    source = inspect.getsource(bot_experience_v5._install_ai_pipeline_upgrade)
    assert "AffichageProgressif(_send)" in source, "l'aperçu doit naître ici"
    assert 'prepare_kwargs["on_delta"] = apercu.afficher' in source
    assert "await apercu.terminer(morceaux[0])" in source, "l'aperçu doit devenir le message final"
    assert "await apercu.abandonner()" in source, "une carte ou une erreur doit le retirer"


@pytest.mark.parametrize(
    "signature, attendu",
    [
        (lambda *, question, on_delta=None: None, True),
        (lambda **kwargs: None, True),
        (lambda *, question, force_web_search=False: None, False),
        (lambda *, question: None, False),
    ],
)
def test_on_delta_n_est_passe_qu_aux_signatures_qui_le_declarent(signature, attendu):
    """Passer un paramètre inconnu a déjà cassé tout le listener (cas image_urls)."""
    assert bot_experience_v5._accepte_on_delta(signature) is attendu


def test_un_objet_sans_signature_ne_fait_pas_planter():
    assert bot_experience_v5._accepte_on_delta(object()) is False
    assert bot_experience_v5._accepte_on_delta(None) is False
