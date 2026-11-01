"""Variantes d'emojis d'application SentriX, dessinées localement sans IA.

96 icônes combinées (16 motifs x 6 états) et 16 GIFs animés.
On reprend les illustrations SentriX existantes (licences internes), mais chaque
combinaison a une silhouette, une pastille et un nom distincts.
Les fichiers sont générés une seule fois sur le disque du conteneur, avant la
synchronisation d'application. AUCUN emoji existant n'est remplacé ou supprimé.
"""
from __future__ import annotations

import io
import math
from pathlib import Path

BASES = (
    "ticket", "security", "mod", "logs", "member_join", "member_leave",
    "economy", "gamepad", "role", "backup", "level", "ai",
    "gift", "calendar", "channel", "message",
)
BADGES = ("success", "lock", "alert", "eye", "clock", "trophy")
ANIMES = frozenset(f"sentrix_live_{nom}" for nom in BASES)
NOMBRE = len(BASES) * len(BADGES) + len(ANIMES)
PALETTES = (
    (66, 200, 131), (108, 95, 230), (242, 155, 67),
    (70, 179, 228), (239, 115, 112), (225, 187, 77),
)

def _fond(draw, couleur, *, alpha=28):
    draw.rounded_rectangle((5, 5, 122, 122), radius=29, fill=(*couleur, alpha))
    draw.rounded_rectangle((5, 5, 122, 122), radius=29, outline=(*couleur, 175), width=3)

def _base(dossier: Path, nom: str):
    from PIL import Image
    for extension in (".png", ".gif"):
        chemin = dossier / f"sentrix_{nom}{extension}"
        if chemin.exists():
            with Image.open(chemin) as image:
                return image.convert("RGBA").copy()
    return None

def _compose(dossier: Path, base: str, badge: str, index: int):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = PALETTES[index % len(PALETTES)]
    _fond(d, color)
    principal = _base(dossier, base)
    secondary = _base(dossier, badge)
    if principal is None or secondary is None:
        return None
    principal.thumbnail((92, 92), Image.Resampling.LANCZOS)
    img.alpha_composite(principal, (10, 12))
    d.ellipse((74, 72, 124, 122), fill=(22, 26, 44, 247),
              outline=(*color, 255), width=4)
    secondary.thumbnail((40, 40), Image.Resampling.LANCZOS)
    img.alpha_composite(secondary, (79, 77))
    # Une barre de couleur qui aide à distinguer même les très petites tailles.
    d.rounded_rectangle((14, 113, 58, 119), radius=3, fill=(*color, 245))
    return img

def _gif(dossier: Path, base: str, index: int):
    from PIL import Image, ImageDraw
    principal = _base(dossier, base)
    if principal is None:
        return None
    principal.thumbnail((87, 87), Image.Resampling.LANCZOS)
    frames = []
    color = PALETTES[index % len(PALETTES)]
    for frame in range(8):
        img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        _fond(draw, color, alpha=15)
        radius = int(42 + 5 * (1 + math.sin(frame * math.tau / 8)))
        center = (64, 64)
        draw.ellipse((center[0]-radius, center[1]-radius,
                      center[0]+radius, center[1]+radius),
                     outline=(*color, 245), width=4)
        img.alpha_composite(principal, (21, 19))
        frames.append(img)
    return frames

def generer(dossier: Path) -> dict[str, int]:
    """Génère seulement les noms absents. Ne touche jamais aux assets d'origine."""
    from PIL import Image
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    faits = 0
    for index, base in enumerate(BASES):
        for couleur_index, badge in enumerate(BADGES):
            cible = dossier / f"sentrix_{base}_{badge}.png"
            if cible.exists():
                continue
            image = _compose(dossier, base, badge, index + couleur_index)
            if image is None:
                continue
            image.save(cible, format="PNG", optimize=True)
            if cible.stat().st_size > 256 * 1024:
                cible.unlink(missing_ok=True)
                continue
            faits += 1
        cible = dossier / f"sentrix_live_{base}.gif"
        if cible.exists():
            continue
        frames = _gif(dossier, base, index)
        if frames is None:
            continue
        frames[0].save(
            cible, save_all=True, append_images=frames[1:],
            optimize=True, duration=110, loop=0, disposal=2,
        )
        if cible.stat().st_size > 256 * 1024:
            cible.unlink(missing_ok=True)
            continue
        faits += 1
    return {"crees": faits, "total_planifies": NOMBRE}
