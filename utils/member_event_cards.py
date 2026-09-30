"""Cartes visuelles automatiques pour les arrivées et départs SentriX."""
from __future__ import annotations

import asyncio
import io
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import aiohttp
import discord
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

_SIZE = (1200, 420)
_MAX_BACKGROUND_BYTES = 8 * 1024 * 1024


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


async def _public_https(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            return False
        infos = await asyncio.to_thread(
            socket.getaddrinfo,
            parsed.hostname,
            parsed.port or 443,
            type=socket.SOCK_STREAM,
        )
        addresses = {item[4][0] for item in infos}
        return bool(addresses) and all(ipaddress.ip_address(addr).is_global for addr in addresses)
    except Exception:
        return False


async def fetch_background_image(url: str | None) -> bytes | None:
    """Télécharge une image publique HTTPS, avec taille et redirections bornées."""
    current = str(url or "").strip()
    if not current:
        return None
    timeout = aiohttp.ClientTimeout(total=8, connect=4)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for _ in range(4):
                if not await _public_https(current):
                    return None
                async with session.get(
                    current,
                    allow_redirects=False,
                    headers={"User-Agent": "SentriX/1.0"},
                ) as response:
                    if 300 <= response.status < 400:
                        location = response.headers.get("Location")
                        if not location:
                            return None
                        current = urljoin(current, location)
                        continue
                    if response.status != 200:
                        return None
                    content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
                    if not content_type.startswith("image/"):
                        return None
                    length = response.content_length
                    if length is not None and length > _MAX_BACKGROUND_BYTES:
                        return None
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        data.extend(chunk)
                        if len(data) > _MAX_BACKGROUND_BYTES:
                            return None
                    return bytes(data)
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        return None
    return None


def _background(kind: str, custom_bytes: bytes | None = None) -> Image.Image:
    """Fond plein écran. Une image choisie devient réellement l'arrière-plan."""
    if custom_bytes:
        try:
            source = Image.open(io.BytesIO(custom_bytes)).convert("RGB")
            image = ImageOps.fit(source, _SIZE, method=Image.Resampling.LANCZOS)
            # Assombrit juste assez pour que le texte reste lisible sans masquer l'image.
            overlay = Image.new("RGBA", _SIZE, (0, 0, 0, 92))
            return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
        except Exception:
            pass

    width, height = _SIZE
    goodbye = str(kind).casefold() == "goodbye"
    top = (35, 36, 41) if goodbye else (31, 32, 37)
    bottom = (17, 18, 21)
    image = Image.new("RGB", _SIZE)
    pixels = image.load()
    for y in range(height):
        t = y / max(1, height - 1)
        for x in range(width):
            d = (x / max(1, width - 1)) * 0.18
            pixels[x, y] = tuple(
                int(a * (1 - t) + b * t + 6 * d)
                for a, b in zip(top, bottom)
            )
    return image


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, start_size: int, min_size: int = 30):
    size = start_size
    while size > min_size:
        font = _font(size, bold=True)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width:
            return font
        size -= 2
    return _font(min_size, bold=True)


def build_member_event_card(
    member: discord.Member,
    *,
    kind: str,
    background_bytes: bytes | None = None,
) -> discord.File:
    """Construit une carte 1200×420 ; l'image choisie remplit tout le background."""
    image = _background(kind, background_bytes).convert("RGBA")
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

    title_font = _fit_text(draw, title, 1040, 56)
    subtitle_font = _fit_text(draw, subtitle, 980, 30, 22)
    brand_font = _font(20, bold=True)
    title_box = draw.textbbox((0, 0), title, font=title_font)
    subtitle_box = draw.textbbox((0, 0), subtitle, font=subtitle_font)

    draw.rounded_rectangle(
        (70, 70, 1130, 350),
        radius=28,
        fill=(8, 9, 12, 118),
        outline=(255, 255, 255, 42),
        width=2,
    )
    draw.text(
        ((1200 - (title_box[2] - title_box[0])) / 2, 128),
        title,
        font=title_font,
        fill=(255, 255, 255, 255),
    )
    draw.text(
        ((1200 - (subtitle_box[2] - subtitle_box[0])) / 2, 212),
        subtitle,
        font=subtitle_font,
        fill=(228, 230, 235, 255),
    )

    count = int(getattr(getattr(member, "guild", None), "member_count", 0) or 0)
    brand = f"SentriX · {count} membre{'s' if count > 1 else ''}" if count else "SentriX"
    brand_box = draw.textbbox((0, 0), brand, font=brand_font)
    draw.text(
        ((1200 - (brand_box[2] - brand_box[0])) / 2, 292),
        brand,
        font=brand_font,
        fill=(190, 193, 201, 255),
    )

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    return discord.File(buffer, filename=filename)


__all__ = ["build_member_event_card", "fetch_background_image"]
