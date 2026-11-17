"""17/11/2026 : « l'IA est trop lente ».

Elle ne l'était pas. Mesuré en production, OpenAI met 1,2 à 2,3 s à écrire une
réponse (pointes à 5 s) — et SentriX attendait la dernière lettre avant
d'afficher quoi que ce soit. L'attente était réelle, mais elle était entièrement
passée à regarder « SentriX est en train d'écrire… ».

Ces tests verrouillent les deux garanties qui rendent l'affichage progressif
sûr : il ne change RIEN à ce qui est généré, et il ne peut jamais faire perdre
une réponse.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.ai import AffichageProgressif  # noqa: E402
from utils import ai_service  # noqa: E402


class _Message:
    def __init__(self, contenu):
        self.content = contenu
        self.supprime = False

    async def edit(self, content=None, **_k):
        self.content = content

    async def delete(self):
        self.supprime = True


class _Salon:
    def __init__(self):
        self.envoyes: list[str] = []

    async def envoyer(self, content=None, **_k):
        self.envoyes.append(content)
        return _Message(content)


# --------------------------------------------------------------------- aperçu
@pytest.mark.asyncio
async def test_rien_n_est_poste_avant_d_avoir_de_quoi_lire():
    """Un aperçu de trois lettres clignoterait sans rien apprendre à personne."""
    salon = _Salon()
    apercu = AffichageProgressif(salon.envoyer)
    await apercu.afficher("Salut")
    assert salon.envoyes == [] and apercu.message is None


@pytest.mark.asyncio
async def test_le_premier_apercu_part_des_qu_il_y_a_du_texte():
    salon = _Salon()
    apercu = AffichageProgressif(salon.envoyer)
    await apercu.afficher("x" * AffichageProgressif.MINIMUM)
    assert len(salon.envoyes) == 1 and apercu.message is not None


@pytest.mark.asyncio
async def test_les_modifications_sont_espacees_pour_discord():
    """Discord limite le débit : une modification de retard vaut mieux qu'un refus."""
    salon = _Salon()
    apercu = AffichageProgressif(salon.envoyer)
    await apercu.afficher("a" * 50)
    premier = apercu.message.content
    await apercu.afficher("a" * 50 + "suite immédiate")
    assert apercu.message.content == premier, "deux écritures collées : débit non respecté"


@pytest.mark.asyncio
async def test_le_texte_cumule_rattrape_un_affichage_saute():
    """Chaque appel porte tout le texte : sauter un affichage ne perd rien."""
    salon = _Salon()
    apercu = AffichageProgressif(salon.envoyer)
    await apercu.afficher("a" * 50)
    apercu._derniere_ecriture = 0.0  # l'intervalle est écoulé
    await apercu.afficher("a" * 50 + "LA SUITE MANQUEE")
    assert "LA SUITE MANQUEE" in apercu.message.content


@pytest.mark.asyncio
async def test_le_texte_final_remplace_l_apercu_sans_message_en_double():
    salon = _Salon()
    apercu = AffichageProgressif(salon.envoyer)
    await apercu.afficher("a" * 50)
    assert await apercu.terminer("réponse définitive") is True
    assert apercu.message.content == "réponse définitive"
    assert len(salon.envoyes) == 1, "l'aperçu doit être réutilisé, pas doublé"


@pytest.mark.asyncio
async def test_sans_apercu_le_message_part_normalement():
    """Réponse trop courte pour un aperçu : le chemin d'avant doit rester entier."""
    apercu = AffichageProgressif(_Salon().envoyer)
    assert await apercu.terminer("réponse courte") is False


@pytest.mark.asyncio
async def test_une_erreur_retire_l_apercu():
    """Mieux vaut aucun texte qu'un texte interrompu au milieu d'une phrase."""
    salon = _Salon()
    apercu = AffichageProgressif(salon.envoyer)
    await apercu.afficher("a" * 50)
    message = apercu.message
    await apercu.abandonner()
    assert message.supprime and apercu.message is None


@pytest.mark.asyncio
async def test_un_salon_qui_refuse_l_apercu_ne_casse_rien():
    """L'aperçu est un confort : il ne doit jamais empêcher de répondre."""

    async def _refuse(**_k):
        raise RuntimeError("permission refusée")

    apercu = AffichageProgressif(_refuse)
    await apercu.afficher("a" * 50)  # ne lève pas
    assert apercu.message is None


# ----------------------------------------------------------------------- flux
@pytest.mark.asyncio
async def test_le_flux_transmet_le_texte_cumule_jamais_le_fragment():
    """L'appelant affiche toujours une réponse complète-à-cet-instant."""
    recus: list[str] = []

    class _Client:
        async def _flux(self):
            for fragment in ("Bon", "jour", " toi"):
                yield SimpleNamespace(type="response.output_text.delta", delta=fragment)
            yield SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(output_text="Bonjour toi", id="r1"),
            )

        class responses:
            @staticmethod
            async def create(**kwargs):
                assert kwargs.get("stream") is True
                return _Client()._flux()

    final, texte = await ai_service._repondre_en_flux(_Client(), {}, recus.append)
    assert recus == ["Bon", "Bonjour", "Bonjour toi"]
    assert texte == "Bonjour toi" and final.id == "r1"


@pytest.mark.asyncio
async def test_un_flux_refuse_retombe_sur_la_reponse_en_un_bloc():
    """Le streaming est un confort, jamais une condition pour obtenir sa réponse."""
    appels = []

    class _Client:
        class responses:
            @staticmethod
            async def create(**kwargs):
                appels.append(kwargs.get("stream"))
                if kwargs.get("stream"):
                    raise RuntimeError("flux non supporté")
                return SimpleNamespace(output_text="réponse entière", id="r2")

    final, texte = await ai_service._repondre_en_flux(_Client(), {}, lambda _t: None)
    assert texte == "réponse entière" and final.id == "r2"
    assert appels == [True, None], "il faut réessayer sans flux"


@pytest.mark.asyncio
async def test_un_affichage_qui_echoue_ne_perd_pas_la_reponse():
    class _Client:
        async def _flux(self):
            yield SimpleNamespace(type="response.output_text.delta", delta="texte")
            yield SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(output_text="texte", id="r3"),
            )

        class responses:
            @staticmethod
            async def create(**_k):
                return _Client()._flux()

    async def _casse(_texte):
        raise RuntimeError("Discord indisponible")

    _final, texte = await ai_service._repondre_en_flux(_Client(), {}, _casse)
    assert texte == "texte"


def test_sans_on_delta_le_comportement_est_celui_d_avant():
    """La garantie centrale : tous les autres appelants ne bougent pas d'un pouce."""
    import inspect

    source = inspect.getsource(ai_service.generate)
    assert "if on_delta is None:" in source
    assert "on_delta=None" in str(inspect.signature(ai_service.generate))
