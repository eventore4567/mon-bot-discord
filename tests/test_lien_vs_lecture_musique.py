"""« donne le lien spotify de X » partait dans le lecteur (21/11/2026).

Captures de l'utilisateur, 15:37 et 15:38 :

- « donne le lien spotify de Loka Loka »  -> « Rejoignez un salon vocal »
- « donne la music ... sur spotif »       -> « URL non reconnue »

Dans les deux cas la personne demandait un LIEN, pas une mise en lecture.
Le lecteur ne sait de toute façon rien faire d'un « sur Spotify » sans
adresse, alors que l'IA a l'outil de recherche web depuis cette semaine.

Nommer une plateforme sans donner d'URL, c'est demander de chercher là-bas.
Une vraie URL, elle, reste une demande de lecture légitime.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from cogs.natural_music_intent_guard import _veut_un_lien_pas_une_lecture as veut_un_lien  # noqa: E402


@pytest.mark.parametrize(
    "question",
    [
        "donne le lien spotify de Loka Loka",        # capture 15:37
        "donne la music souremener besamer sur spotif",  # capture 15:38
        "trouve la video youtube de la finale 2022",
        "c koi le lien deezer de ce son",
        "envoie moi l url du site officiel",
        "cherche sur soundcloud",
    ],
)
def test_une_demande_de_lien_va_a_l_ia(question):
    assert veut_un_lien(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "mets la musique Loka Loka",
        "play Loka Loka",
        "pause la musique",
        "monte le volume",
        "skip",
        "mets le son plus fort",
        "reprends la lecture",
    ],
)
def test_une_vraie_demande_de_lecture_reste_au_lecteur(question):
    """Le correctif ne doit pas casser le lecteur : c'est la moitié qui compte."""
    assert veut_un_lien(question) is False


def test_une_vraie_url_reste_une_lecture():
    """Nommer une plateforme AVEC son adresse, c'est vouloir l'écouter."""
    assert veut_un_lien("joue https://open.spotify.com/track/abc") is False
    assert veut_un_lien("mets https://youtube.com/watch?v=abc") is False
    # Sans adresse, en revanche, il n'y a rien à jouer.
    assert veut_un_lien("joue ce son sur spotify") is True


def test_le_garde_est_bien_pose_avant_la_recherche_de_commande():
    """Placé après, il n'aurait servi à rien : la commande était déjà choisie."""
    import inspect

    from cogs import natural_music_intent_guard as garde

    source = inspect.getsource(garde.install)
    avant = source.split("command_line = original(")[0]
    assert "_veut_un_lien_pas_une_lecture(question)" in avant
