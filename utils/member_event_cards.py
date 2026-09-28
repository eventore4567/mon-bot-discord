"""Cartes visuelles automatiques pour les arrivées et départs SentriX."""
from __future__ import annotations

import io

import discord
from PIL import Image, ImageDraw, ImageFilter, ImageFont

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


def _background(kind: str) -> Image.Image:
    """Fond toujours visible, généré localement : aucun asset externe requis."""
    width, height = _SIZE
    goodbye = str(kind).casefold() == "goodbye"

    top = (74, 31, 103) if goodbye else (46, 38, 126)
    bottom = (16, 18, 37) if goodbye else (10, 24, 59)
    image = Image.new("RGB", _SIZE)
    pixels = image.load()

    for y in range(height):
        t = y / max(1, height - 1)
        for x in range(width):
            center_glow = 1.0 - min(1.0, abs(x - width * 0.58) / (width * 0.58))
            r = int(top[0] * (1 - t) + bottom[0] * t + 20 * center_glow)
            g = int(top[1] * (1 - t) + bottom[1] * t + 12 * center_glow)
            b = int(top[2] * (1 - t) + bottom[2] * t + 38 * center_glow)
            pixels[x, y] = (min(r, 255), min(g, 255), min(b, 255))

    glow = Image.new("RGBA", _SIZE, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    accent = (236, 76, 146, 125) if goodbye else (130, 92, 255, 140)
    gd.ellipse((670, -180, 1320, 470), fill=accent)
    gd.ellipse((-260, 180, 380, 700), fill=(58, 176, 255, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(86))
    image = Image.alpha_composite(image.convert("RGBA"), glow)

    lines = Image.new("RGBA", _SIZE, (0, 0, 0, 0))
    ld = ImageDraw.Draw(lines)
    for x in range(-350, 1500, 150):
        ld.line((x, height, x + 430, 0), fill=(255, 255, 255, 22), width=2)

    return Image.alpha_composite(image, lines).convert("RGB")


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    start_size: int,
    min_size: int = 30,
):
    size = start_size
    while size > min_size:
        font = _font(size, bold=True)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width:
            return font
        size -= 2
    return _font(min_size, bold=True)


def build_member_event_card(member: discord.Member, *, kind: str) -> discord.File:
    """Construit une carte 1200×420 avec fond, texte et identité dynamique."""
    image = _background(kind).convert("RGBA")
    draw = ImageDraw.Draw(image)

    name = (
        getattr(member, "display_name", None)
        or getattr(member, "name", None)
        or "Membre"
    ).strip()
    server = (
        getattr(getattr(member, "guild", None), "name", None)
        or "le serveur"
    ).strip()

    if str(kind).casefold() == "goodbye":
        title = f"Au revoir {name}"
        subtitle = f"Merci d’avoir fait partie de {server}."
        filename = "sentrix_goodbye.png"
    else:
        title = f"Bienvenue {name}"
        subtitle = f"Heureux de t’accueillir sur {server}."
        filename = "sentrix_welcome.png"

    title_font = _fit_text(draw, title, 1040, 66)
    subtitle_font = _fit_text(draw, subtitle, 980, 34, 24)
    brand_font = _font(24, bold=True)

    title_box = draw.textbbox((0, 0), title, font=title_font)
    subtitle_box = draw.textbbox((0, 0), subtitle, font=subtitle_font)

    draw.rounded_rectangle(
        (55, 55, 1145, 365),
        radius=34,
        fill=(7, 10, 22, 112),
        outline=(255, 255, 255, 52),
        width=2,
    )
    draw.text(
        ((1200 - (title_box[2] - title_box[0])) / 2, 125),
        title,
        font=title_font,
        fill=(255, 255, 255, 255),
    )
    draw.text(
        ((1200 - (subtitle_box[2] - subtitle_box[0])) / 2, 220),
        subtitle,
        font=subtitle_font,
        fill=(225, 229, 241, 255),
    )

    count = int(
        getattr(getattr(member, "guild", None), "member_count", 0) or 0
    )
    brand = (
        f"SentriX  •  {count} membre{'s' if count > 1 else ''}"
        if count
        else "SentriX"
    )
    brand_box = draw.textbbox((0, 0), brand, font=brand_font)
    draw.text(
        ((1200 - (brand_box[2] - brand_box[0])) / 2, 300),
        brand,
        font=brand_font,
        fill=(199, 191, 255, 255),
    )

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    return discord.File(buffer, filename=filename)


__all__ = ["build_member_event_card"]
