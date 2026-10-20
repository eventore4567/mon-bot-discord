"""Bande décorative *ultra-fine* commune à tous les journaux SentriX.

La bande sert exclusivement à proposer une image au ratio très horizontal
aux Components V2 de Discord. Elle n'affiche aucune donnée, marque, catégorie,
texte ni couleur par type d'événement. Discord décide de la largeur effective
des composants ; le ratio 1200×24 ne garantit pas une carte plein écran.

Les images des utilisateurs (messages/vidéos) restent gérées séparément.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from utils.log_banners import ROOT

# À largeur d'affichage ~600 px, le ratio 50:1 représente environ 12 px.
SIZE = (1200, 24)
VERSION = 3
BANNER_DIR = ROOT / "assets" / "premium_log_banners"
BANNER_FILENAME = f"sentrix_neutral_strip_{VERSION}.png"


def build_premium_banner(log_type: str = "") -> Image.Image:
    """Même image RGBA très discrète pour chaque catégorie de logs.

    Pixels totalement transparents, à l'exception d'une ligne grise
    translucide sur le bord inférieur. Compatible thèmes clair et sombre.
    """
    image = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.line((0, SIZE[1] - 1, SIZE[0] - 1, SIZE[1] - 1), fill=(135, 139, 146, 18))
    return image


def get_premium_log_banner(log_type: str = "", title: str = "") -> Path:
    """Réutilise un seul PNG pour tous les types et événements."""
    path = BANNER_DIR / BANNER_FILENAME
    if path.is_file():
        return path
    BANNER_DIR.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    image = build_premium_banner(log_type)
    image.save(temp, format="PNG", optimize=True)
    temp.replace(path)
    return path


__all__ = ["SIZE", "VERSION", "BANNER_FILENAME", "build_premium_banner", "get_premium_log_banner"]
