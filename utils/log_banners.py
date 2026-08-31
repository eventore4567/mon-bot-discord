"""Génération et sélection des bannières de logs SentriX."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

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
SOURCE_BANNERS: dict[str, Path] = {
    kind: BANNER_DIR / f"banner_source_{kind}.webp" for kind in COLORS
}
_READY = False


def _mix(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _load_approved_banner(kind: str) -> Image.Image | None:
    source = SOURCE_BANNERS.get(kind)
    if source is None or not source.exists():
        return None
    try:
        with Image.open(source) as opened:
            return ImageOps.fit(
                opened.convert("RGBA"),
                (WIDTH, HEIGHT),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
    except (OSError, ValueError):
        return None


def _build_background(left: tuple[int, int, int], right: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
    pixels = image.load()
    halo_x, halo_y = WIDTH * 0.34, HEIGHT * 0.42
    halo_rx, halo_ry = WIDTH * 0.54, HEIGHT * 1.65
    for y in range(HEIGHT):
        yn = y / max(1, HEIGHT - 1)
        vertical_bend = math.sin(yn * math.pi) * 0.055
        for x in range(WIDTH):
            xn = x / max(1, WIDTH - 1)
            curved_t = _clamp(xn + vertical_bend * (0.55 - xn))
            curved_t = curved_t * curved_t * (3.0 - 2.0 * curved_t)
            r, g, b = (_mix(left[i], right[i], curved_t) for i in range(3))
            dx, dy = (x - halo_x) / halo_rx, (y - halo_y) / halo_ry
            radial = _clamp(1.0 - math.sqrt(dx * dx + dy * dy)) ** 2
            center_light = 1.0 - abs(yn * 2.0 - 1.0)
            lift = 0.88 + center_light * 0.08 + radial * 0.20
            vignette = _clamp((xn - 0.62) / 0.38)
            vf = 1.0 - vignette * vignette * 0.28
            pixels[x, y] = tuple(min(255, round(v * lift * vf)) for v in (r, g, b)) + (255,)
    stripes = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(stripes)
    for start in range(-HEIGHT * 2, WIDTH + HEIGHT * 2, 138):
        draw.polygon([(start, HEIGHT), (start + 88, HEIGHT), (start + 180, 0), (start + 92, 0)], fill=(255, 255, 255, 12))
    return Image.alpha_composite(image, stripes.filter(ImageFilter.GaussianBlur(1.5)))


def _composite_logo(image: Image.Image, accent: tuple[int, int, int]) -> Image.Image:
    if not LOGO_PATH.exists():
        return image
    try:
        with Image.open(LOGO_PATH) as opened:
            logo = opened.convert("RGBA")
    except (OSError, ValueError):
        return image
    scale = min(210 / max(1, logo.width), 86 / max(1, logo.height), 1.0)
    size = (max(1, round(logo.width * scale)), max(1, round(logo.height * scale)))
    if size != logo.size:
        logo = logo.resize(size, Image.Resampling.LANCZOS)
    x, y = (WIDTH - logo.width) // 2, (HEIGHT - logo.height) // 2
    alpha = logo.getchannel("A")
    halo_mask = Image.new("L", (WIDTH, HEIGHT), 0)
    halo_mask.paste(alpha, (x, y))
    halo_mask = halo_mask.filter(ImageFilter.GaussianBlur(13))
    halo = Image.new("RGBA", (WIDTH, HEIGHT), (*accent, 0))
    halo.putalpha(halo_mask.point(lambda value: min(125, round(value * 0.50))))
    image = Image.alpha_composite(image, halo)
    image.alpha_composite(logo, (x, y))
    return image


def ensure_banners(force: bool = False) -> None:
    global _READY
    if _READY and not force:
        return
    BANNER_DIR.mkdir(parents=True, exist_ok=True)
    for kind, (left, right) in COLORS.items():
        path = BANNER_DIR / f"banner_{kind}.png"
        if path.exists() and not force:
            continue
        image = _load_approved_banner(kind) or _composite_logo(_build_background(left, right), left)
        image.save(path, "PNG", optimize=True)
    _READY = True


def banner_kind(log_type: str, title: str = "", description: str = "") -> str:
    """Le registre événementiel est prioritaire ; le texte n'est qu'un repli legacy."""
    from utils.log_categories import resolve
    return resolve(log_type, title, description)[2]


def get_banner(log_type: str, title: str = "", description: str = "") -> Path:
    ensure_banners()
    kind = banner_kind(log_type, title, description)
    path = BANNER_DIR / f"banner_{kind}.png"
    if not path.exists():
        ensure_banners(force=True)
    return path


ensure_banners(force=True)

__all__ = [
    "BANNER_DIR", "COLORS", "HEIGHT", "LOGO_PATH", "SOURCE_BANNERS", "WIDTH",
    "banner_kind", "ensure_banners", "get_banner",
]
