"""Une attaque ne montre plus toujours la même animation.

Demandé par Jayden le 2026-10-17 : « quand on attaque ça monte un GIF
d'attaque, pas le même à chaque fois ». Jusqu'ici une scène valait une
seule image, donc chaque coup affichait exactement le même GIF.

La contrainte à respecter est écrite dans utils/game_visuals : pas de
tirage au hasard, parce qu'un panneau de jeu est réédité à chaque clic et
qu'une image tirée au sort clignoterait en plein tour. La variation est
donc DÉTERMINISTE — le numéro de tour sert de graine.

Aucune URL n'a été inventée : les variantes sont les liens déjà déclarés
et vérifiés, dont les scènes « boss-* » qui existaient sans jamais être
choisies par scene_for.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from utils import game_visuals as gv


def test_une_attaque_dispose_de_plusieurs_animations():
    assert len(gv.urls_de_scene("fight")) >= 5


def test_deux_tours_consecutifs_ne_montrent_pas_la_meme_image():
    vues = [gv.url_de_scene("fight", tour) for tour in range(5)]
    assert len(set(vues)) == 5, "les tours se répètent trop vite"


def test_le_meme_tour_rejoue_donne_exactement_la_meme_image():
    """Sans cela, l'animation clignoterait entre deux clics du même tour."""
    for tour in range(8):
        assert gv.url_de_scene("fight", tour) == gv.url_de_scene("fight", tour)


def test_sans_graine_le_comportement_est_celui_d_avant():
    """Les 120 appels qui ne passent pas de graine ne changent pas."""
    assert gv.url_de_scene("fight") == gv.GIFS["fight"]
    assert gv.url_de_scene("win") == gv.GIFS["win"]


@pytest.mark.parametrize("scene", sorted(gv.VARIANTES))
def test_aucune_variante_n_invente_d_url(scene):
    """Toute variante doit être une URL déjà déclarée et vérifiée."""
    connues = set(gv.GIFS.values())
    for url in gv.urls_de_scene(scene):
        assert url in connues, f"{url} n'est pas dans GIFS"


@pytest.mark.parametrize("scene", sorted(gv.VARIANTES))
def test_chaque_variante_a_sa_propre_cle_de_cache(scene):
    """Deux images différentes ne doivent pas se télescoper.

    Les octets sont mis en cache et la pièce jointe est nommée d'après la
    clé : sans clé par variante, le deuxième GIF d'une scène afficherait
    les octets du premier.
    """
    urls = gv.urls_de_scene(scene)
    cles = [gv._cle_variante(scene, u) for u in urls]
    assert len(set(cles)) == len(urls)
    assert cles[0] == scene, "la variante canonique garde le nom de la scène"


def test_une_graine_non_numerique_reste_stable():
    """Un identifiant de message est une chaîne : le choix doit être reproductible."""
    a = gv.url_de_scene("fight", "message-123")
    b = gv.url_de_scene("fight", "message-123")
    assert a == b
    assert a in gv.urls_de_scene("fight")


def test_le_combat_de_boss_passe_bien_son_numero_de_tour():
    import inspect

    from cogs import games_economy

    src = inspect.getsource(games_economy)
    assert 'graine=getattr(self, "turn", 0)' in src, (
        "le combat doit semer l'animation avec son tour, sinon rien ne varie"
    )
