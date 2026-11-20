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


# --------------------------------------------------- revue Codex du 17/11/2026
@pytest.mark.asyncio
async def test_l_apercu_ne_publie_pas_ce_que_les_filtres_refusent():
    """Les filtres de sortie tournaient APRÈS le flux : l'aperçu les contournait.

    ai_service vérifie contains_sensitive_content après la fin du flux, et
    ai_context_v9 appelle ai_safety.filtrer après le retour de generate.
    Supprimer l'aperçu ensuite n'annule pas ce qui a déjà été lu sur Discord.
    """
    from cogs.ai import AffichageProgressif

    envoyes = []

    async def _envoyer(**kwargs):
        envoyes.append(kwargs)
        raise AssertionError("un texte refusé ne doit JAMAIS partir sur Discord")

    apercu = AffichageProgressif(_envoyer)
    apercu._refuse_par_les_filtres = staticmethod(lambda texte: True)
    await apercu.afficher("un texte que les filtres rejettent")
    assert envoyes == []
    assert apercu.message is None
    # Et le blocage est définitif : la suite du texte contient toujours ce début.
    await apercu.afficher("un texte que les filtres rejettent, et la suite")
    assert envoyes == []
    assert await apercu.terminer("peu importe") is False


@pytest.mark.asyncio
async def test_un_texte_propre_passe_toujours():
    from cogs.ai import AffichageProgressif

    envoyes = []

    async def _envoyer(**kwargs):
        envoyes.append(kwargs)
        return object()

    apercu = AffichageProgressif(_envoyer)
    await apercu.afficher("bonjour, voici une réponse parfaitement ordinaire")
    assert len(envoyes) == 1


def test_un_filtre_en_panne_fait_taire_l_apercu(monkeypatch):
    """En cas de doute on ne publie pas : c'est le seul choix sûr."""
    from cogs.ai import AffichageProgressif
    from utils import ai_service

    def _casse(_texte):
        raise RuntimeError("filtre indisponible")

    monkeypatch.setattr(ai_service, "contains_sensitive_content", _casse)
    assert AffichageProgressif._refuse_par_les_filtres("un texte ordinaire") is True


def test_un_texte_vide_ne_declenche_pas_le_blocage():
    """Les filtres ignorent le vide : ce n'est pas une panne."""
    from cogs.ai import AffichageProgressif

    assert AffichageProgressif._refuse_par_les_filtres("") is False


def test_la_carte_recupere_la_reference_de_reponse():
    """L'aperçu consommait l'unique réponse native et ne la rendait pas."""
    source = inspect.getsource(bot_experience_v5._install_ai_pipeline_upgrade)
    carte = source.split("doit_etre_en_carte(content)")[1][:600]
    assert "await apercu.abandonner()" in carte
    assert "replied_once = False" in carte, "la première carte doit citer la question"
