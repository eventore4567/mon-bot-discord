"""Les émojis animés SentriX sont dessinés, pas téléchargés.

Demandé par Jayden le 2026-10-23 : « des émojis personnalisés animés,
simples, stylés — un bouclier qui rebondit, une flèche animée, une croix
qui se fait — pas des émojis moches ».

Ils sont générés par tools/generer_emojis_animes.py. Chaque image est
tracée à 4× puis réduite en LANCZOS : sans ce sur-échantillonnage, les
diagonales d'une croix ou d'une flèche sortent crénelées à 128 px, et
c'est exactement ce qui fait « émoji moche ».

Deux formes ont été refaites après les avoir regardées : le bouclier,
d'abord un pentagone étroit qui se lisait comme un médiator, et la
flèche, d'abord un chevron de trait fin qui se lisait comme un « > ».
"""
from __future__ import annotations

import os
import pathlib

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest
from PIL import Image

from utils import sentrix_emojis

NOUVEAUX = [
    "sentrix_bouclier", "sentrix_valide", "sentrix_croix",
    "sentrix_fleche", "sentrix_chargement", "sentrix_alerte",
]


def _chemin(nom: str) -> pathlib.Path:
    chemin = sentrix_emojis.fichier(nom)
    assert chemin is not None, f"{nom} introuvable"
    return chemin


@pytest.mark.parametrize("nom", NOUVEAUX)
def test_l_emoji_existe_et_est_un_gif(nom):
    assert _chemin(nom).suffix == ".gif"


@pytest.mark.parametrize("nom", NOUVEAUX)
def test_l_emoji_est_reellement_anime(nom):
    with Image.open(_chemin(nom)) as img:
        assert getattr(img, "n_frames", 1) > 1, f"{nom} n'a qu'une image"


@pytest.mark.parametrize("nom", NOUVEAUX)
def test_l_emoji_tient_dans_les_limites_de_discord(nom):
    chemin = _chemin(nom)
    assert chemin.stat().st_size < 256_000, "Discord refuse au-delà de 256 Kio"
    with Image.open(chemin) as img:
        assert img.size == (128, 128)


@pytest.mark.parametrize("nom", NOUVEAUX)
def test_le_fond_reste_transparent(nom):
    """Un fond opaque ferait une vignette grise dans Discord."""
    with Image.open(_chemin(nom)) as img:
        coins = img.convert("RGBA")
        for xy in ((0, 0), (127, 0), (0, 127), (127, 127)):
            assert coins.getpixel(xy)[3] == 0, f"{nom} : coin {xy} opaque"


@pytest.mark.parametrize("nom", NOUVEAUX)
def test_l_emoji_est_declare_comme_anime(nom):
    """Sans cette déclaration, c'est le .png qui serait servi s'il existait."""
    assert nom in sentrix_emojis.ANIMES_AUTORISES


# Couverture mesurée au milieu de la boucle. Un anneau couvre forcément moins
# qu'une forme pleine : le compte-tours tient 4,7 % là où le bouclier en fait
# 23 %, et c'est normal. Le seuil distingue donc les deux familles plutôt que
# d'imposer un chiffre unique qui condamnerait l'anneau.
COUVERTURE_MINIMALE = {
    "sentrix_chargement": 0.030,   # anneau fin
}
COUVERTURE_PAR_DEFAUT = 0.070


@pytest.mark.parametrize("nom", NOUVEAUX)
def test_la_forme_occupe_vraiment_la_toile(nom):
    """Garde contre le premier jet : une flèche trop maigre se lisait « > »."""
    with Image.open(_chemin(nom)) as img:
        img.seek(img.n_frames // 2)
        alpha = img.convert("RGBA").getchannel("A")
    plein = sum(1 for p in alpha.getdata() if p > 40)
    ratio = plein / (128 * 128)
    seuil = COUVERTURE_MINIMALE.get(nom, COUVERTURE_PAR_DEFAUT)
    assert ratio > seuil, f"{nom} : forme trop petite ({ratio:.1%}, seuil {seuil:.1%})"


def test_le_generateur_reste_dans_le_depot():
    """Les sources doivent pouvoir être regénérées, pas seulement les GIF."""
    assert pathlib.Path("tools/generer_emojis_animes.py").is_file()
