#!/usr/bin/env python3
"""Génère les émojis animés SentriX.

Les émojis sont dessinés ici, pas téléchargés : on maîtrise le trait, la
palette et le poids, et rien ne dépend d'un CDN qui peut disparaître.

Qualité : chaque image est tracée à 4× puis réduite en LANCZOS. Sans ce
sur-échantillonnage, les diagonales d'une croix ou d'une flèche sortent
crénelées à 128 px, et c'est précisément ce qui fait « émoji moche ».

    python3 tools/generer_emojis_animes.py [--out assets/sentrix_emojis]
"""
from __future__ import annotations

import argparse
import math
import pathlib

from PIL import Image, ImageDraw, ImageFilter

TAILLE = 128
ECHELLE = 4          # sur-échantillonnage
IMAGES = 14          # images par boucle
DUREE_MS = 70

VIOLET = (124, 58, 237)
BLEU = (59, 130, 246)
VERT = (34, 197, 94)
ROUGE = (239, 68, 68)
AMBRE = (245, 158, 11)
BLANC = (255, 255, 255)


def _toile() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (TAILLE * ECHELLE, TAILLE * ECHELLE), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _reduire(img: Image.Image) -> Image.Image:
    return img.resize((TAILLE, TAILLE), Image.LANCZOS)


def _adoucir(t: float) -> float:
    """Accélère puis ralentit : un mouvement linéaire fait « robot »."""
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))


def _halo(img: Image.Image, couleur: tuple[int, int, int], force: float) -> Image.Image:
    """Lueur douce derrière la forme, pour détacher l'émoji du fond Discord."""
    if force <= 0:
        return img
    halo = img.filter(ImageFilter.GaussianBlur(radius=10 * ECHELLE * force))
    teinte = Image.new("RGBA", img.size, couleur + (0,))
    teinte.putalpha(halo.getchannel("A").point(lambda a: int(a * 0.55 * force)))
    return Image.alpha_composite(teinte, img)


# ----------------------------------------------------------------- formes

def _silhouette_bouclier(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    """Écu courbe : épaules carrées, flancs galbés, pointe basse.

    Le premier essai était un pentagone — ça donnait une forme molle qui ne se
    lisait pas comme un bouclier à 32 px. Les flancs sont donc échantillonnés
    sur une courbe, et la pointe est franche.
    """
    # Proportions : un écu est plus LARGE que haut dans sa partie basse. Le
    # premier jet était étroit et pointu, il se lisait comme un médiator.
    haut, demi, hauteur = cy - r * 0.80, r * 0.92, r * 1.58
    points = [(cx - demi, haut), (cx + demi, haut)]
    # Flanc droit : épaule franche, puis galbe qui ne s'accélère que vers le bas.
    for i in range(1, 25):
        t = i / 24
        x = cx + demi * (1 - t ** 2.6)
        points.append((x, haut + hauteur * t))
    for i in range(24, 0, -1):
        t = i / 24
        x = cx - demi * (1 - t ** 2.6)
        points.append((x, haut + hauteur * t))
    return points


def emoji_bouclier() -> list[Image.Image]:
    """Un bouclier qui rebondit, avec un reflet doux qui le balaie."""
    images = []
    c = TAILLE * ECHELLE / 2
    r = TAILLE * ECHELLE * 0.33
    for i in range(IMAGES):
        t = i / IMAGES
        img, d = _toile()
        rebond = math.sin(t * 2 * math.pi) * 6 * ECHELLE
        forme = _silhouette_bouclier(c, c + rebond, r)
        d.polygon(forme, fill=VIOLET + (255,))

        # Reflet : un bandeau flouté, donc sans bord dur, découpé à la forme.
        bande = Image.new("RGBA", img.size, (0, 0, 0, 0))
        db = ImageDraw.Draw(bande)
        x = c - r * 1.6 + (3.2 * r) * t
        db.polygon([(x, c - r * 1.2), (x + r * 0.34, c - r * 1.2),
                    (x - r * 0.34, c + r * 1.2), (x - r * 0.68, c + r * 1.2)],
                   fill=BLANC + (120,))
        bande = bande.filter(ImageFilter.GaussianBlur(radius=4 * ECHELLE))
        masque = Image.new("L", img.size, 0)
        ImageDraw.Draw(masque).polygon(forme, fill=255)
        vide = Image.new("RGBA", img.size, (0, 0, 0, 0))
        img = Image.alpha_composite(img, Image.composite(bande, vide, masque))
        images.append(_reduire(_halo(img, VIOLET, 0.35)))
    return images


def _trace_progressif(d, points, couleur, epais, avancement):
    """Dessine une polyligne partiellement, pour un trait qui « s'écrit »."""
    if avancement <= 0:
        return
    longueurs = [math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
    total = sum(longueurs) or 1
    reste = total * avancement
    tracés = [points[0]]
    for i, seg in enumerate(longueurs):
        if reste >= seg:
            tracés.append(points[i + 1])
            reste -= seg
        else:
            ratio = reste / seg
            x = points[i][0] + (points[i + 1][0] - points[i][0]) * ratio
            y = points[i][1] + (points[i + 1][1] - points[i][1]) * ratio
            tracés.append((x, y))
            break
    if len(tracés) >= 2:
        d.line(tracés, fill=couleur + (255,), width=int(epais), joint="curve")
        for p in tracés:
            d.ellipse([p[0] - epais / 2, p[1] - epais / 2, p[0] + epais / 2, p[1] + epais / 2],
                      fill=couleur + (255,))


def emoji_valide() -> list[Image.Image]:
    """Une coche qui s'écrit, puis respire."""
    images = []
    c = TAILLE * ECHELLE / 2
    r = TAILLE * ECHELLE * 0.34
    pts = [(c - r * 0.85, c), (c - r * 0.18, c + r * 0.62), (c + r * 0.88, c - r * 0.62)]
    for i in range(IMAGES):
        t = i / IMAGES
        img, d = _toile()
        if t < 0.55:
            _trace_progressif(d, pts, VERT, 13 * ECHELLE, _adoucir(t / 0.55))
        else:
            pulse = 1 + 0.07 * math.sin((t - 0.55) / 0.45 * math.pi)
            agrandis = [(c + (x - c) * pulse, c + (y - c) * pulse) for x, y in pts]
            _trace_progressif(d, agrandis, VERT, 13 * ECHELLE, 1.0)
        images.append(_reduire(_halo(img, VERT, 0.30)))
    return images


def emoji_croix() -> list[Image.Image]:
    """Une croix qui se trace, une branche après l'autre."""
    images = []
    c = TAILLE * ECHELLE / 2
    r = TAILLE * ECHELLE * 0.30
    a = [(c - r, c - r), (c + r, c + r)]
    b = [(c + r, c - r), (c - r, c + r)]
    for i in range(IMAGES):
        t = i / IMAGES
        img, d = _toile()
        _trace_progressif(d, a, ROUGE, 13 * ECHELLE, _adoucir(min(1.0, t / 0.40)))
        if t > 0.35:
            _trace_progressif(d, b, ROUGE, 13 * ECHELLE, _adoucir(min(1.0, (t - 0.35) / 0.40)))
        images.append(_reduire(_halo(img, ROUGE, 0.30)))
    return images


def emoji_fleche() -> list[Image.Image]:
    """Une flèche épaisse qui glisse vers la droite, avec une traînée.

    Le premier essai était un simple chevron de trait fin : à la taille d'un
    émoji il se lisait comme un « > », pas comme une flèche. Elle a maintenant
    une hampe et une tête, et occupe franchement la toile.
    """
    images = []
    c = TAILLE * ECHELLE / 2
    r = TAILLE * ECHELLE * 0.36
    def tracer(d, x, alpha):
        epais = r * 0.40
        # Hampe.
        d.line([(x - r * 0.95, c), (x + r * 0.18, c)], fill=BLEU + (alpha,),
               width=int(epais), joint="curve")
        # Tête.
        d.polygon([(x - r * 0.06, c - r * 0.62), (x + r * 0.92, c), (x - r * 0.06, c + r * 0.62)],
                  fill=BLEU + (alpha,))
    for i in range(IMAGES):
        t = i / IMAGES
        img, d = _toile()
        glisse = (_adoucir(t) - 0.5) * r * 0.55
        for decal, alpha in ((-r * 0.70, 45), (-r * 0.36, 100), (0, 255)):
            tracer(d, c + glisse + decal, alpha)
        images.append(_reduire(_halo(img, BLEU, 0.30)))
    return images


def emoji_chargement() -> list[Image.Image]:
    """Un arc qui tourne, sans à-coup à la boucle."""
    images = []
    c = TAILLE * ECHELLE / 2
    r = TAILLE * ECHELLE * 0.33
    epais = 11 * ECHELLE
    boite = [c - r, c - r, c + r, c + r]
    for i in range(IMAGES):
        t = i / IMAGES
        img, d = _toile()
        d.arc(boite, 0, 360, fill=VIOLET + (55,), width=int(epais))
        debut = t * 360
        d.arc(boite, debut, debut + 110, fill=VIOLET + (255,), width=int(epais))
        images.append(_reduire(_halo(img, VIOLET, 0.25)))
    return images


def emoji_alerte() -> list[Image.Image]:
    """Un triangle d'alerte qui pulse."""
    images = []
    c = TAILLE * ECHELLE / 2
    for i in range(IMAGES):
        t = i / IMAGES
        img, d = _toile()
        pulse = 1 + 0.06 * math.sin(t * 2 * math.pi)
        r = TAILLE * ECHELLE * 0.36 * pulse
        d.polygon([(c, c - r * 0.92), (c + r * 0.88, c + r * 0.66), (c - r * 0.88, c + r * 0.66)],
                  fill=AMBRE + (255,))
        d.line([(c, c - r * 0.34), (c, c + r * 0.20)], fill=(40, 24, 0, 255), width=int(10 * ECHELLE))
        d.ellipse([c - 6 * ECHELLE, c + r * 0.34, c + 6 * ECHELLE, c + r * 0.34 + 12 * ECHELLE],
                  fill=(40, 24, 0, 255))
        images.append(_reduire(_halo(img, AMBRE, 0.30)))
    return images


def emoji_musique() -> list[Image.Image]:
    """Une double croche dont les notes montent et descendent en boucle.

    Les deux têtes bougent en décalé : en phase, le mouvement se lit comme un
    simple glissement vertical de tout le symbole, pas comme de la musique.
    """
    images = []
    for i in range(IMAGES):
        img, d = _toile()
        c = TAILLE * ECHELLE / 2
        r = TAILLE * ECHELLE * 0.30
        trait = int(TAILLE * ECHELLE * 0.065)
        for rang, decalage in ((0, 0.0), (1, 0.5)):
            t = _adoucir(((i / IMAGES) + decalage) % 1.0)
            monte = (t - 0.5) * r * 0.30
            x = c - r * 0.45 + rang * r * 0.95
            y = c + r * 0.55 + monte
            tete = r * 0.26
            d.ellipse([x - tete, y - tete * 0.78, x + tete, y + tete * 0.78],
                      fill=VIOLET if rang == 0 else BLEU)
            d.line([(x + tete * 0.92, y), (x + tete * 0.92, y - r * 1.05)],
                   fill=VIOLET if rang == 0 else BLEU, width=trait)
        # La barre qui relie les deux hampes : c'est elle qui fait « double croche ».
        haut = c + r * 0.55 - r * 1.05
        d.line([(c - r * 0.45 + r * 0.24, haut), (c + r * 0.50 + r * 0.24, haut)],
               fill=BLEU, width=trait)
        images.append(_reduire(_halo(img, VIOLET, 0.35)))
    return images


def emoji_notification() -> list[Image.Image]:
    """Une cloche qui sonne : elle oscille, le battant suit avec un retard.

    Un battant synchrone donnerait une cloche rigide ; c'est le retard qui
    donne l'impression du son.
    """
    images = []
    for i in range(IMAGES):
        img, d = _toile()
        c = TAILLE * ECHELLE / 2
        r = TAILLE * ECHELLE * 0.30
        phase = math.sin(2 * math.pi * i / IMAGES)
        incline = phase * r * 0.16
        # Corps : un arc fermé par une base droite.
        d.pieslice([c - r + incline, c - r * 0.95, c + r + incline, c + r * 0.95],
                   180, 360, fill=AMBRE)
        d.rectangle([c - r + incline, c, c + r + incline, c + r * 0.42], fill=AMBRE)
        d.rounded_rectangle(
            [c - r * 1.12 + incline, c + r * 0.42, c + r * 1.12 + incline, c + r * 0.62],
            radius=r * 0.1, fill=AMBRE,
        )
        retard = math.sin(2 * math.pi * (i - 2) / IMAGES) * r * 0.22
        d.ellipse([c - r * 0.17 + retard, c + r * 0.66,
                   c + r * 0.17 + retard, c + r * 1.00], fill=AMBRE)
        images.append(_reduire(_halo(img, AMBRE, 0.40)))
    return images


EMOJIS = {
    "sentrix_bouclier": emoji_bouclier,
    "sentrix_valide": emoji_valide,
    "sentrix_croix": emoji_croix,
    "sentrix_fleche": emoji_fleche,
    "sentrix_chargement": emoji_chargement,
    "sentrix_alerte": emoji_alerte,
    "sentrix_musique": emoji_musique,
    "sentrix_notification": emoji_notification,
}


def _ecrire_gif(images: list[Image.Image], chemin: pathlib.Path) -> int:
    """GIF transparent : un index de palette est réservé au vide."""
    cadres = []
    for img in images:
        alpha = img.getchannel("A")
        p = img.convert("RGB").quantize(colors=255, method=Image.MEDIANCUT)
        p.paste(255, (0, 0), alpha.point(lambda a: 255 if a < 128 else 0))
        cadres.append(p)
    cadres[0].save(
        chemin, save_all=True, append_images=cadres[1:], duration=DUREE_MS,
        loop=0, disposal=2, transparency=255, optimize=True,
    )
    return chemin.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="assets/sentrix_emojis")
    args = parser.parse_args()
    dossier = pathlib.Path(args.out)
    dossier.mkdir(parents=True, exist_ok=True)
    for nom, fabrique in EMOJIS.items():
        chemin = dossier / f"{nom}.gif"
        poids = _ecrire_gif(fabrique(), chemin)
        etat = "ok" if poids < 256_000 else "TROP LOURD"
        print(f"  {nom:22s} {poids // 1024:>4} Kio  {etat}")


if __name__ == "__main__":
    main()
