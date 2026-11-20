"""« Il met du temps à comprendre » — il ne pouvait rien chercher (20/11/2026).

Capture de l'utilisateur : « donne la music souremener besamer sur spotif je
conais le titre » → « Envoie-moi le titre exact ». Il VENAIT de donner le
titre. Quatre allers-retours plus tôt, « donne le lien pour trouver la music
loka loka » avait reçu « Tu parles de Loka Loka ? ».

Ce n'était pas de l'incompréhension. L'outil de recherche web n'était fourni au
modèle QUE si la question contenait l'une d'une vingtaine de chaînes
littérales : « donne moi le lien » passait, « donne le lien » non, et
« spotify » n'y figurait pas du tout. Sans outil, un modèle ne peut
qu'interroger l'utilisateur.

Deux changements : l'outil est toujours proposé (le modèle décide), et la
consigne lui dit de chercher avant de redemander.
"""
from __future__ import annotations

import inspect
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from utils import ai_conversation, ai_service  # noqa: E402


# ------------------------------------- les phrases réelles qui échouaient
@pytest.mark.parametrize(
    "phrase",
    [
        "donne le lien poru trouver la music loka loka",
        "donne la music souremener besamer sur spotif je conais le le titre",
        "donne le lien",
        "envoie le site officiel",
        "spotify",
        "cherche moi l url du site",
        "quel est le dernier film de nolan",
    ],
)
def test_ces_demandes_forcent_la_recherche(phrase):
    assert ai_service.needs_web_search(phrase) is True


@pytest.mark.parametrize(
    "phrase",
    ["salut ca va", "mdr tkt", "ouais je suis là", "😂", "bah ya quoi mdr"],
)
def test_le_bavardage_ne_force_rien(phrase):
    """Forcer une recherche sur « salut ça va » coûterait du temps pour rien."""
    assert ai_service.needs_web_search(phrase) is False


# --------------------------------- l'outil est proposé même sans mot-clé
def test_l_outil_est_toujours_fourni_au_modele():
    """Le cœur du correctif : une liste de mots-clés ne doit plus pouvoir
    EMPÊCHER le modèle de chercher."""
    source = inspect.getsource(ai_service.generate)
    assert 'kwargs["tools"] = [{"type": "web_search"' in source, (
        "l'outil doit être attaché à chaque appel"
    )
    assert '"required" if web_search else "auto"' in source, (
        "forcé sur demande explicite, au choix du modèle sinon"
    )


def test_la_recherche_video_garde_ses_domaines_et_reste_forcee():
    source = inspect.getsource(ai_service.generate)
    bloc = source.split("if video_search:")[1].split("else:")[0]
    assert "allowed_domains" in bloc
    assert '"required"' in bloc


def test_l_outil_n_est_jamais_absent():
    """Aucune branche ne doit laisser le modèle sans outil de recherche."""
    source = inspect.getsource(ai_service.generate)
    assert source.count('kwargs["tools"]') == 2, (
        "exactement deux branches : vidéo, et tout le reste"
    )


# ------------------------------------------- chercher plutôt que redemander
def test_la_consigne_dit_de_chercher_avant_de_redemander():
    consigne = ai_conversation.CONSIGNE_CONVERSATION
    assert "CHERCHE AVANT DE REDEMANDER" in consigne
    assert "mal orthographié" in consigne, "un titre approximatif doit être corrigé, pas rejeté"
    assert "QUE si la recherche n'a rien donné" in consigne, "redemander reste permis, mais en dernier"
