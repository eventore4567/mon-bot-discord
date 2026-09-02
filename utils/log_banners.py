"""Génération des bannières de logs SentriX (1024x110, cinq variantes).

Le style vient du registre ``LOG_REGISTRY`` via ``utils.log_categories.resolve`` : la
couleur est déterminée par le ``log_type``, jamais devinée depuis le titre. Deviner était
cassé — « unban » contient « ban », donc un débannissement sortait en rouge. La détection
textuelle ne subsiste que comme repli, à l'intérieur de ``canonical_event_type``, quand le
``log_type`` est inconnu du registre.

Composition d'une bannière :
- dégradé horizontal courbé (la ligne de mélange s'incurve verticalement) ;
- halo radial décentré ;
- bandes diagonales très discrètes ;
- vignettage sur le bord droit ;
- liseré lumineux sur le bord haut ;
- logo ``assets/sentrix_logo.png`` centré avec un halo à la couleur d'accent.

Le logo est facultatif : s'il est absent, la bannière se génère sans lever.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

logger = logging.getLogger("bot.log-banners")

ROOT = Path(__file__).resolve().parents[1]
BANNER_DIR = ROOT / "assets" / "log_banners"

# Logo de la bannière, par ordre de préférence. assets/sentrix_logo.png n'existe pas dans
# le dépôt : on retombe sur la marque déjà présente. Déposer sentrix_logo.png suffit à
# prendre la main sans toucher au code.
_LOGO_CANDIDATES = (
    ROOT / "assets" / "sentrix_logo.png",
    ROOT / "assets" / "sentrix" / "brand.png",
)


def _resolve_logo():
    for candidate in _LOGO_CANDIDATES:
        if candidate.exists():
            return candidate
    return _LOGO_CANDIDATES[0]


LOGO_PATH = _resolve_logo()
WIDTH = 1024
HEIGHT = 110

# Le dégradé est calculé à cette largeur puis étiré en LANCZOS jusqu'à WIDTH. Un dégradé
# est lisse par construction : le rendu est identique à l'œil, pour 4x moins de pixels
# calculés en Python pur au démarrage.
_GRADIENT_WIDTH = 256

# Familles de bannieres. Cinq etats (les quatre premiers plus « special »), puis
# quatre domaines. On s'arrete la volontairement : une famille par domaine reste
# reconnaissable, une par commande ne le serait plus, et chaque variante est une
# image de plus a garder coherente.
COLORS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    # Etats
    "error": ((255, 62, 82), (126, 17, 48)),
    "success": ((42, 221, 119), (12, 100, 67)),
    "warning": ((255, 188, 60), (176, 78, 18)),
    "info": ((55, 151, 255), (51, 67, 198)),
    "special": ((174, 97, 255), (76, 38, 180)),
    # Domaines : une identite propre la ou la teinte d'etat ne dit rien d'utile.
    "moderation": ((232, 84, 106), (104, 22, 46)),   # rouge sourd, distinct de l'erreur
    "security": ((139, 122, 255), (58, 40, 148)),    # indigo, la couleur des protections
    "economy": ((240, 190, 78), (146, 92, 20)),      # or
    "config": ((64, 208, 214), (22, 96, 132)),       # cyan, les reglages
}
STYLES = tuple(COLORS)

# WebP plutot que PNG : la banniere part en piece jointe a CHAQUE message, et le
# meme visuel pese 5 Ko au lieu de 45. Sur un degrade avec logo, la difference ne
# se voit pas ; sur la bande passante d'un gros serveur, si.
EXTENSION = "webp"
_QUALITE_WEBP = 88


def nom_fichier(style: str) -> str:
    """Nom du fichier de banniere pour une famille."""
    return f"banner_{style}.{EXTENSION}"
_READY = False


def _mix(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _build_gradient(left: tuple[int, int, int], right: tuple[int, int, int]) -> Image.Image:
    """Dégradé courbé + halo radial décentré + vignettage droit, en basse résolution."""
    image = Image.new("RGB", (_GRADIENT_WIDTH, HEIGHT))
    pixels = image.load()
    halo_x, halo_y = _GRADIENT_WIDTH * 0.34, HEIGHT * 0.42
    halo_rx, halo_ry = _GRADIENT_WIDTH * 0.54, HEIGHT * 1.65
    last_x = max(1, _GRADIENT_WIDTH - 1)
    last_y = max(1, HEIGHT - 1)

    for y in range(HEIGHT):
        yn = y / last_y
        # La ligne de mélange s'incurve : le dégradé n'est pas une verticale plate.
        vertical_bend = math.sin(yn * math.pi) * 0.055
        center_light = 1.0 - abs(yn * 2.0 - 1.0)
        dy = (y - halo_y) / halo_ry
        dy2 = dy * dy
        for x in range(_GRADIENT_WIDTH):
            xn = x / last_x
            curved = _clamp(xn + vertical_bend * (0.55 - xn))
            curved = curved * curved * (3.0 - 2.0 * curved)  # smoothstep
            dx = (x - halo_x) / halo_rx
            radial = _clamp(1.0 - math.sqrt(dx * dx + dy2)) ** 2
            lift = 0.88 + center_light * 0.08 + radial * 0.20
            vignette = _clamp((xn - 0.62) / 0.38)
            fade = 1.0 - vignette * vignette * 0.28
            factor = lift * fade
            pixels[x, y] = (
                min(255, round(_mix(left[0], right[0], curved) * factor)),
                min(255, round(_mix(left[1], right[1], curved) * factor)),
                min(255, round(_mix(left[2], right[2], curved) * factor)),
            )

    return image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS).convert("RGBA")


def _add_stripes(image: Image.Image) -> Image.Image:
    """Bandes diagonales très discrètes (alpha 12/255), floutées pour rester sourdes."""
    stripes = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(stripes)
    for start in range(-HEIGHT * 2, WIDTH + HEIGHT * 2, 138):
        draw.polygon(
            [(start, HEIGHT), (start + 88, HEIGHT), (start + 180, 0), (start + 92, 0)],
            fill=(255, 255, 255, 12),
        )
    return Image.alpha_composite(image, stripes.filter(ImageFilter.GaussianBlur(1.5)))


def _add_top_edge(image: Image.Image) -> Image.Image:
    """Liseré lumineux sur le bord haut : 1 px franc, puis une retombée douce."""
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle([(0, 0), (WIDTH - 1, 0)], fill=(255, 255, 255, 96))
    for offset in range(1, 5):
        alpha = round(52 * (1.0 - offset / 5.0))
        draw.rectangle([(0, offset), (WIDTH - 1, offset)], fill=(255, 255, 255, alpha))
    return Image.alpha_composite(image, overlay)


def _composite_logo(image: Image.Image, accent: tuple[int, int, int]) -> Image.Image:
    """Logo centré avec halo. Absence du fichier = bannière rendue telle quelle."""
    if not LOGO_PATH.exists():
        return image
    try:
        with Image.open(LOGO_PATH) as opened:
            logo = opened.convert("RGBA")
    except (OSError, ValueError):
        logger.warning("Logo illisible (%s) : bannière générée sans logo.", LOGO_PATH)
        return image

    scale = min(210 / max(1, logo.width), 82 / max(1, logo.height), 1.0)
    size = (max(1, round(logo.width * scale)), max(1, round(logo.height * scale)))
    if size != logo.size:
        logo = logo.resize(size, Image.Resampling.LANCZOS)

    x, y = (WIDTH - logo.width) // 2, (HEIGHT - logo.height) // 2
    halo_mask = Image.new("L", (WIDTH, HEIGHT), 0)
    halo_mask.paste(logo.getchannel("A"), (x, y))
    halo_mask = halo_mask.filter(ImageFilter.GaussianBlur(13))
    halo = Image.new("RGBA", (WIDTH, HEIGHT), (*accent, 0))
    halo.putalpha(halo_mask.point(lambda value: min(125, round(value * 0.50))))
    image = Image.alpha_composite(image, halo)
    image.alpha_composite(logo, (x, y))
    return image


def build_banner(style: str) -> Image.Image:
    left, right = COLORS.get(style, COLORS["info"])
    image = _build_gradient(left, right)
    image = _add_stripes(image)
    image = _add_top_edge(image)
    return _composite_logo(image, left)


def ensure_banners(force: bool = False) -> None:
    """Genere une banniere par famille. ``force=True`` regenere le cache disque.

    Les fichiers sont ecrits une seule fois au demarrage, puis relus depuis le
    disque a chaque envoi : aucune image n'est recalculee par commande.
    """
    global _READY
    if _READY and not force:
        return
    BANNER_DIR.mkdir(parents=True, exist_ok=True)
    for style in COLORS:
        path = BANNER_DIR / nom_fichier(style)
        if path.exists() and not force:
            continue
        try:
            build_banner(style).save(path, "WEBP", quality=_QUALITE_WEBP, method=6)
        except Exception:
            logger.exception("Génération de la bannière %s impossible.", style)
    _READY = True


def banner_kind(log_type: str, title: str = "", description: str = "") -> str:
    """Le registre événementiel décide ; le texte n'est qu'un repli."""
    from utils.log_categories import resolve
    return resolve(log_type, title, description)[2]


def get_banner(log_type: str, title: str = "", description: str = "") -> Path:
    ensure_banners()
    path = BANNER_DIR / nom_fichier(banner_kind(log_type, title, description))
    if not path.exists():
        ensure_banners(force=True)
    return path


# Une seule régénération au démarrage. Une erreur Pillow ne doit jamais bloquer le boot :
# send_wide_log détecte l'absence de bannière et le trace (SXTRACE 6 BANNER_MISSING).
try:
    ensure_banners(force=True)
except Exception:  # pragma: no cover - dépend de l'environnement de rendu
    logger.exception("Régénération des bannières au démarrage impossible.")

__all__ = [
    "BANNER_DIR", "COLORS", "HEIGHT", "LOGO_PATH", "STYLES", "WIDTH",
    "banner_kind", "build_banner", "ensure_banners", "get_banner",
]
