"""Cartes visuelles automatiques pour les arrivées et départs SentriX."""
from __future__ import annotations

import io
from pathlib import Path

import discord
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_BACKGROUND = _ROOT / "assets" / "sentrix" / "card-background-v5.png"
_SIZE = (1200, 420)


def _font(size: int, *, bold: bool = False):
    names = (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _background() -> Image.Image:
    if _DEFAULT_BACKGROUND.exists():
        with Image.open(_DEFAULT_BACKGROUND) as source:
            bg = ImageOps.fit(source.convert("RGB"), _SIZE, method=Image.Resampling.LANCZOS)
            return ImageEnhance.Contrast(bg).enhance(1.06)
    return Image.new("RGB", _SIZE, (18, 20, 28))


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, start_size: int, min_size: int = 30):
    size = start_size
    while size > min_size:
        font = _font(size, bold=True)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width:
            return font
        size -= 2
    return _font(min_size, bold=True)


def build_member_event_card(member: discord.Member, *, kind: str) -> discord.File:
    """Construit une carte 1200×420 avec texte dynamique, sans requête réseau."""
    image = _background().convert("RGBA")
    overlay = Image.new("RGBA", image.size, (7, 9, 15, 122))
    image = Image.alpha_composite(image, overlay)

    draw = ImageDraw.Draw(image)
    name = (getattr(member, "display_name", None) or getattr(member, "name", None) or "Membre").strip()
    server = (getattr(getattr(member, "guild", None), "name", None) or "le serveur").strip()

    if str(kind).casefold() == "goodbye":
        title = f"Au revoir {name}"
        subtitle = f"Merci d'avoir fait partie de {server}."
        filename = "sentrix_goodbye.png"
    else:
        title = f"Bienvenue {name}"
        subtitle = f"Heureux de t'accueillir sur {server}."
        filename = "sentrix_welcome.png"

    title_font = _fit_text(draw, title, 1040, 66)
    subtitle_font = _font(32, bold=False)
    brand_font = _font(24, bold=True)

    title_box = draw.textbbox((0, 0), title, font=title_font)
    title_w = title_box[2] - title_box[0]
    subtitle_box = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    subtitle_w = subtitle_box[2] - subtitle_box[0]

    draw.rounded_rectangle((55, 55, 1145, 365), radius=34, fill=(11, 13, 21, 150), outline=(255, 255, 255, 32), width=2)
    draw.text(((1200 - title_w) / 2, 132), title, font=title_font, fill=(255, 255, 255, 255))
    draw.text(((1200 - subtitle_w) / 2, 225), subtitle, font=subtitle_font, fill=(219, 222, 232, 255))

    count = int(getattr(getattr(member, "guild", None), "member_count", 0) or 0)
    brand = f"SentriX  •  {count} membre{'s' if count > 1 else ''}" if count else "SentriX"
    brand_box = draw.textbbox((0, 0), brand, font=brand_font)
    draw.text(((1200 - (brand_box[2] - brand_box[0])) / 2, 300), brand, font=brand_font, fill=(185, 176, 255, 255))

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    return discord.File(buffer, filename=filename)


__all__ = ["build_member_event_card"]
