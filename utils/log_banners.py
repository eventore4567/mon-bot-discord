"""Génération et sélection des bannières de logs SentriX.

Les cinq bannières sont stockées dans ``assets/log_banners`` afin que le renderer
Components V2 puisse les joindre comme premier média du message. Elles sont régénérées
au démarrage pour éviter qu'un ancien PNG en cache conserve l'ancien design.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
BANNER_DIR = ROOT / "assets" / "log_banners"
LOGO_PATH = ROOT / "assets" / "sentrix_logo.png"

WIDTH = 1024
HEIGHT = 110

COLORS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "error": ((255, 62, 82), (126, 17, 48)),
    "success": ((42, 221, 119), (12, 100, 67)),
    "warning": ((255, 188, 60), (176, 78, 18)),
    "info": ((55, 151, 255), (51, 67, 198)),
    "special": ((174, 97, 255), (76, 38, 180)),
}

_READY = False


def _mix(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _build_background(
    left: tuple[int, int, int],
    right: tuple[int, int, int],
) -> Image.Image:
    """Construit le fond premium : courbe, halo, bandes, vignette et liseré."""
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
    pixels = image.load()

    halo_x = WIDTH * 0.34
    halo_y = HEIGHT * 0.42
    halo_rx = WIDTH * 0.54
    halo_ry = HEIGHT * 1.65

    for y in range(HEIGHT):
        yn = y / max(1, HEIGHT - 1)
        vertical_bend = math.sin(yn * math.pi) * 0.055
        for x in range(WIDTH):
            xn = x / max(1, WIDTH - 1)

            # Smoothstep + légère courbure verticale pour éviter un gradient plat.
            curved_t = _clamp(xn + vertical_bend * (0.55 - xn))
            curved_t = curved_t * curved_t * (3.0 - 2.0 * curved_t)

            r = _mix(left[0], right[0], curved_t)
            g = _mix(left[1], right[1], curved_t)
            b = _mix(left[2], right[2], curved_t)

            # Halo radial décentré vers le tiers gauche.
            dx = (x - halo_x) / halo_rx
            dy = (y - halo_y) / halo_ry
            radial = _clamp(1.0 - math.sqrt(dx * dx + dy * dy))
            radial = radial * radial

            # Léger modelé vertical pour donner du volume.
            center_light = 1.0 - abs(yn * 2.0 - 1.0)
            lift = 0.88 + center_light * 0.08 + radial * 0.20

            # Vignettage progressif à droite.
            vignette = _clamp((xn - 0.62) / 0.38)
            vignette_factor = 1.0 - vignette * vignette * 0.28

            pixels[x, y] = (
                min(255, round(r * lift * vignette_factor)),
                min(255, round(g * lift * vignette_factor)),
                min(255, round(b * lift * vignette_factor)),
                255,
            )

    # Bandes diagonales très discrètes.
    stripes = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(stripes)
    for start in range(-HEIGHT * 2, WIDTH + HEIGHT * 2, 138):
        draw.polygon(
            [
                (start, HEIGHT),
                (start + 88, HEIGHT),
                (start + 180, 0),
                (start + 92, 0),
            ],
            fill=(255, 255, 255, 12),
        )
    stripes = stripes.filter(ImageFilter.GaussianBlur(1.5))
    image = Image.alpha_composite(image, stripes)

    # Liseré lumineux supérieur, très fin, avec diffusion.
    top_glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(top_glow)
    glow_draw.rectangle((0, 0, WIDTH, 2), fill=(*left, 180))
    glow_draw.rectangle((0, 2, WIDTH, 4), fill=(255, 255, 255, 36))
    top_glow = top_glow.filter(ImageFilter.GaussianBlur(2.0))
    image = Image.alpha_composite(image, top_glow)

    return image


def _composite_logo(image: Image.Image, accent: tuple[int, int, int]) -> Image.Image:
    """Centre le logo SentriX avec un halo ; l'absence du fichier reste non bloquante."""
    if not LOGO_PATH.exists():
        return image

    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
    except (OSError, ValueError):
        return image

    max_w = 210
    max_h = 86
    scale = min(max_w / max(1, logo.width), max_h / max(1, logo.height), 1.0)
    size = (
        max(1, round(logo.width * scale)),
        max(1, round(logo.height * scale)),
    )
    if size != logo.size:
        logo = logo.resize(size, Image.Resampling.LANCZOS)

    x = (WIDTH - logo.width) // 2
    y = (HEIGHT - logo.height) // 2

    # Halo derrière le logo à partir de son canal alpha.
    alpha = logo.getchannel("A")
    halo_mask = Image.new("L", (WIDTH, HEIGHT), 0)
    halo_mask.paste(alpha, (x, y))
    halo_mask = halo_mask.filter(ImageFilter.GaussianBlur(13))
    halo = Image.new("RGBA", (WIDTH, HEIGHT), (*accent, 0))
    halo.putalpha(halo_mask.point(lambda value: min(125, round(value * 0.50))))
    image = Image.alpha_composite(image, halo)

    # Petite ombre douce pour conserver la lisibilité sur toutes les couleurs.
    shadow_mask = Image.new("L", (WIDTH, HEIGHT), 0)
    shadow_mask.paste(alpha, (x, y + 2))
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(4))
    shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    shadow.putalpha(shadow_mask.point(lambda value: min(115, round(value * 0.45))))
    image = Image.alpha_composite(image, shadow)

    image.alpha_composite(logo, (x, y))
    return image


def ensure_banners(force: bool = False) -> None:
    """Génère les cinq bannières premium, sans jamais dépendre de la présence du logo."""
    global _READY

    if _READY and not force:
        return

    BANNER_DIR.mkdir(parents=True, exist_ok=True)

    for kind, (left, right) in COLORS.items():
        path = BANNER_DIR / f"banner_{kind}.png"
        if path.exists() and not force:
            continue

        image = _build_background(left, right)
        image = _composite_logo(image, left)
        image.save(path, "PNG", optimize=True)

    _READY = True


# Ordre de priorité : les actions spécifiques sont évaluées avant les mots génériques.
# Ainsi « unban » est vert avant que « ban » puisse être détecté en rouge.
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "success",
        (
            "unban", "déban", "deban", "unmute", "untimeout",
            "restaur", "réussi", "reussi", "succès", "succes",
            "activé", "active", "ajouté", "ajoute", "levé", "leve",
        ),
    ),
    (
        "special",
        (
            "arrivée", "arrivee", "rejoint", "bienvenue", "welcome",
            "boost", "special", "spécial", "anniversaire", "niveau",
        ),
    ),
    (
        "warning",
        (
            "warn", "avert", "mute", "timeout", "permission",
            "automod", "anti-spam", "antispam", "attention",
            "manquant", "échec", "echec", "refus",
        ),
    ),
    (
        "error",
        (
            "supprim", "delete", "ban", "kick", "expuls",
            "sanction", "erreur", "error", "départ", "depart",
            "quitté", "quitte", "blacklist", "purge",
        ),
    ),
)


def banner_kind(log_type: str, title: str = "", description: str = "") -> str:
    """Retourne ``error/success/warning/info/special`` pour un événement de log."""
    text = f"{log_type} {title} {description}".casefold()

    for kind, words in _RULES:
        if any(word in text for word in words):
            return kind

    return "info"


def get_banner(log_type: str, title: str = "", description: str = "") -> Path:
    """Retourne la bannière voulue et la recrée si elle a été supprimée à chaud."""
    ensure_banners()
    kind = banner_kind(log_type, title, description)
    path = BANNER_DIR / f"banner_{kind}.png"

    if not path.exists():
        ensure_banners(force=True)

    return path


# Le module est importé pendant le démarrage du bot : on écrase ici les anciens PNG en cache.
ensure_banners(force=True)


__all__ = [
    "BANNER_DIR",
    "COLORS",
    "HEIGHT",
    "LOGO_PATH",
    "WIDTH",
    "banner_kind",
    "ensure_banners",
    "get_banner",
]
