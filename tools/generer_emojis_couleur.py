#!/usr/bin/env python3
"""Version colorée et animée de chaque icône SentriX (03/11/2026).

Jayden : « rends tous les emojis animés et colorés ». Les icônes d'origine sont
des glyphes blancs fixes. Pour chacune, ce module dessine ``sentrix_c_<nom>.gif`` :

- le glyphe est teinté d'un dégradé à la couleur de son sens (rouge pour une
  sanction, vert pour une réussite, or pour l'économie…) ; une icône déjà en
  couleur garde ses couleurs ;
- un reflet clair traverse l'icône puis elle respire légèrement.

Les fichiers d'origine ne sont jamais modifiés et l'emoji d'origine garde son nom
(et donc son identifiant dans les anciens messages) : la version animée est un
emoji d'application à part, que ``utils.sentrix_emojis`` préfère quand il existe.

    python3 tools/generer_emojis_couleur.py [--out assets/sentrix_emojis]
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

PREFIXE = "sentrix_"
PREFIXE_ANIME = "sentrix_c_"
TAILLE = 128
IMAGES = 12
DUREE_MS = 85
LIMITE_OCTETS = 256 * 1024

#: (mots-clés, couleur claire, couleur foncée). Le premier mot trouvé dans le
#: nom gagne : l'état (succès, alerte…) passe donc avant le thème.
TEINTES: tuple[tuple[tuple[str, ...], tuple[int, int, int], tuple[int, int, int]], ...] = (
    (("error", "close", "croix", "ban", "delete", "trash", "off", "kick", "mute", "deny", "leave"),
     (255, 120, 120), (220, 38, 38)),
    (("alert", "alerte", "warning", "raid", "scam", "spam", "priority"),
     (255, 200, 90), (234, 120, 12)),
    (("success", "valide", "verified", "check", "unlock", "join", "online"),
     (110, 240, 160), (22, 163, 74)),
    (("trophy", "crown", "level", "dollar", "coin", "bank", "wallet", "economy", "money", "gift", "shop", "slot"),
     (255, 226, 120), (217, 140, 10)),
    (("lock", "security", "shield", "bouclier", "captcha", "mod", "hammer", "case", "admin", "key"),
     (125, 180, 255), (37, 99, 235)),
    (("ai", "bot", "brain", "magic", "typing", "processing", "scan"),
     (220, 150, 255), (147, 51, 234)),
    (("music", "musique", "voice", "mic", "video", "headphone", "sound"),
     (255, 140, 200), (219, 39, 119)),
    (("clock", "calendar", "reminder", "timer", "loading", "chargement", "sync"),
     (120, 225, 255), (8, 145, 178)),
    (("ticket", "message", "chat", "note", "file", "logs", "channel", "info"),
     (130, 200, 255), (59, 130, 246)),
)
DEFAUT = ((180, 160, 255), (109, 40, 217))


def nom_anime(nom: str) -> str:
    """``sentrix_ticket`` -> ``sentrix_c_ticket`` (32 caractères au plus)."""
    base = nom[len(PREFIXE):] if nom.startswith(PREFIXE) else nom
    return (PREFIXE_ANIME + base)[:32]


def teinte(nom: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    mots = nom[len(PREFIXE):].split("_") if nom.startswith(PREFIXE) else nom.split("_")
    for cles, clair, fonce in TEINTES:
        if any(mot in cles for mot in mots):
            return clair, fonce
    for cles, clair, fonce in TEINTES:  # « antiscam », « member_join »…
        if any(cle in nom for cle in cles if len(cle) > 3):
            return clair, fonce
    return DEFAUT


def _deja_colore(image) -> bool:
    """Vrai si l'icône porte déjà de vraies couleurs (variantes à pastille)."""
    from PIL import ImageStat

    hsv = image.convert("RGB").convert("HSV")
    masque = image.getchannel("A").point(lambda a: 255 if a > 40 else 0)
    if not masque.getbbox():
        return False
    return ImageStat.Stat(hsv.getchannel("S"), masque).mean[0] > 60


def _degrade(clair, fonce):
    from PIL import Image

    # Dégradé diagonal : clair en haut à gauche, foncé en bas à droite.
    pas = Image.linear_gradient("L").resize((TAILLE, TAILLE)).rotate(45, expand=False)
    haut = Image.new("RGBA", (TAILLE, TAILLE), clair + (255,))
    bas = Image.new("RGBA", (TAILLE, TAILLE), fonce + (255,))
    return Image.composite(bas, haut, pas)


def _images(source, clair, fonce) -> list:
    from PIL import Image, ImageDraw, ImageFilter

    source = source.convert("RGBA").resize((TAILLE, TAILLE), Image.LANCZOS)
    alpha = source.getchannel("A")
    if _deja_colore(source):
        corps = source.copy()
    else:
        # Garde le modelé du glyphe (zones grisées) en multipliant par sa luminance.
        lum = source.convert("L")
        corps = Image.composite(_degrade(clair, fonce), Image.new("RGBA", source.size, fonce + (255,)), lum)
        corps.putalpha(alpha)
    images = []
    for i in range(IMAGES):
        t = i / IMAGES
        # Respiration : 92 % -> 100 % -> 92 %.
        echelle = 0.92 + 0.08 * (0.5 - 0.5 * math.cos(math.tau * t))
        cote = max(1, int(round(TAILLE * echelle)))
        forme = corps.resize((cote, cote), Image.LANCZOS)
        cadre = Image.new("RGBA", (TAILLE, TAILLE), (0, 0, 0, 0))
        decalage = (TAILLE - cote) // 2
        cadre.alpha_composite(forme, (decalage, decalage))
        # Reflet : une bande claire qui traverse l'icône sur la première moitié.
        if t < 0.55:
            x = int(-TAILLE * 0.6 + (TAILLE * 2.2) * (t / 0.55))
            bande = Image.new("L", (TAILLE, TAILLE), 0)
            ImageDraw.Draw(bande).polygon(
                [(x, 0), (x + 26, 0), (x - 34, TAILLE), (x - 60, TAILLE)], fill=150
            )
            bande = bande.filter(ImageFilter.GaussianBlur(6))
            masque = Image.composite(bande, Image.new("L", bande.size, 0), cadre.getchannel("A"))
            blanc = Image.new("RGBA", cadre.size, (255, 255, 255, 0))
            blanc.putalpha(masque)
            cadre = Image.alpha_composite(cadre, blanc)
        images.append(cadre)
    return images


def _gif(images: list, cible: Path) -> None:
    """GIF à transparence franche : Discord n'accepte pas d'alpha partiel en GIF."""
    from PIL import Image

    sorties = []
    for image in images:
        a = image.getchannel("A")
        opaque = a.point(lambda v: 255 if v >= 110 else 0)
        rgb = image.convert("RGB").quantize(colors=255, method=Image.Quantize.FASTOCTREE)
        rgb.paste(255, mask=opaque.point(lambda v: 255 - v))
        rgb.info["transparency"] = 255
        sorties.append(rgb)
    sorties[0].save(
        cible, save_all=True, append_images=sorties[1:], duration=DUREE_MS,
        loop=0, disposal=2, transparency=255, optimize=False,
    )


def a_animer(dossier: Path) -> list[str]:
    """Icônes PNG qui n'ont encore aucune version animée."""
    dossier = Path(dossier)
    noms = []
    for png in sorted(dossier.glob(f"{PREFIXE}*.png")):
        nom = png.stem
        if nom.startswith(PREFIXE_ANIME) or nom.startswith(f"{PREFIXE}pack_v"):
            continue
        if (dossier / f"{nom}.gif").exists():
            continue  # déjà animée d'origine (bouclier, chargement…)
        noms.append(nom)
    return noms


def generer(dossier: Path) -> dict[str, int]:
    """Crée les GIF manquants. Idempotent, ne touche jamais aux originaux."""
    from PIL import Image

    dossier = Path(dossier)
    faits = ignores = 0
    for nom in a_animer(dossier):
        cible = dossier / f"{nom_anime(nom)}.gif"
        if cible.exists():
            continue
        try:
            with Image.open(dossier / f"{nom}.png") as source:
                clair, fonce = teinte(nom)
                _gif(_images(source, clair, fonce), cible)
        except Exception:  # noqa: BLE001 — une icône ratée ne bloque pas les autres
            cible.unlink(missing_ok=True)
            ignores += 1
            continue
        if cible.stat().st_size > LIMITE_OCTETS:
            cible.unlink(missing_ok=True)
            ignores += 1
            continue
        faits += 1
    return {"crees": faits, "ignores": ignores}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "assets" / "sentrix_emojis"))
    print(generer(Path(parser.parse_args().out)))
