"""Cartes visuelles cohérentes pour Bienvenue, Départ et Niveau SentriX."""
from __future__ import annotations

import asyncio
import io
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import aiohttp
import discord
from PIL import Image, ImageDraw, ImageFont, ImageOps

_SIZE = (1200, 420)
_MAX_BACKGROUND_BYTES = 8 * 1024 * 1024
_ACCENT = (108, 92, 231)
_TEXT = (246, 247, 249)
_MUTED = (181, 185, 194)


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


async def read_member_avatar(member: discord.Member) -> bytes | None:
    """Lit une version PNG de l'avatar sans faire échouer l'évènement si le CDN répond mal."""
    avatar = getattr(member, "avatar", None) or getattr(member, "display_avatar", None)
    if avatar is None:
        return None
    try:
        avatar = avatar.replace(format="png", size=256)
    except (TypeError, ValueError, AttributeError):
        pass
    try:
        data = await asyncio.wait_for(avatar.read(), timeout=4)
        return bytes(data) if data else None
    except Exception:
        return None


def _neutral_background(custom_bytes: bytes | None = None) -> Image.Image:
    """Fond sobre SentriX ; une image configurée remplit réellement toute la carte."""
    if custom_bytes:
        try:
            source = Image.open(io.BytesIO(custom_bytes)).convert("RGB")
            image = ImageOps.fit(source, _SIZE, method=Image.Resampling.LANCZOS).convert("RGBA")
            shade = Image.new("RGBA", _SIZE, (0, 0, 0, 105))
            return Image.alpha_composite(image, shade)
        except Exception:
            pass

    small = Image.new("RGB", (64, 24))
    pixels = small.load()
    left = (20, 21, 25)
    right = (31, 32, 38)
    for y in range(24):
        for x in range(64):
            t = (x / 63) * 0.72 + ((23 - y) / 23) * 0.28
            pixels[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(left, right))
    return small.resize(_SIZE, Image.Resampling.BICUBIC).convert("RGBA")


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, start_size: int, min_size: int = 26):
    size = start_size
    clean = str(text or "").strip()
    while size > min_size:
        font = _font(size, bold=True)
        box = draw.textbbox((0, 0), clean, font=font)
        if box[2] - box[0] <= max_width:
            return clean, font
        size -= 2
    font = _font(min_size, bold=True)
    value = clean
    while value and draw.textbbox((0, 0), value + "…", font=font)[2] > max_width:
        value = value[:-1].rstrip()
    return (value + "…") if value != clean else clean, font


def _paste_avatar(canvas: Image.Image, avatar_bytes: bytes | None, name: str) -> None:
    x, y, size = 88, 103, 214
    ring = Image.new("RGBA", (size + 18, size + 18), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse(
        (2, 2, size + 15, size + 15),
        fill=(19, 20, 24, 245),
        outline=(*_ACCENT, 255),
        width=6,
    )
    canvas.alpha_composite(ring, (x - 9, y - 9))

    if avatar_bytes:
        try:
            avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            avatar = ImageOps.fit(avatar, (size, size), method=Image.Resampling.LANCZOS)
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
            canvas.paste(avatar, (x, y), mask)
            return
        except Exception:
            pass

    draw = ImageDraw.Draw(canvas)
    draw.ellipse((x, y, x + size, y + size), fill=(44, 46, 54, 255))
    initial = (str(name or "?").strip()[:1] or "?").upper()
    font = _font(88, bold=True)
    box = draw.textbbox((0, 0), initial, font=font)
    draw.text(
        (x + (size - (box[2] - box[0])) / 2, y + 48),
        initial,
        font=font,
        fill=_TEXT,
    )


def build_member_event_card(
    member: discord.Member,
    *,
    kind: str,
    background_bytes: bytes | None = None,
    avatar_bytes: bytes | None = None,
    level: int | None = None,
) -> discord.File:
    """Même composition visuelle pour arrivée, départ et montée de niveau."""
    kind = str(kind or "welcome").casefold()
    image = _neutral_background(background_bytes)
    draw = ImageDraw.Draw(image, "RGBA")

    name = str(
        getattr(member, "display_name", None)
        or getattr(member, "name", None)
        or "Membre"
    ).strip()
    guild = getattr(member, "guild", None)
    server = str(getattr(guild, "name", None) or "le serveur").strip()
    count = int(getattr(guild, "member_count", 0) or 0)

    # Carte centrale : assez dense pour ne plus donner l'impression d'un grand vide.
    draw.rounded_rectangle(
        (42, 44, 1158, 376),
        radius=30,
        fill=(10, 11, 14, 178),
        outline=(255, 255, 255, 34),
        width=2,
    )
    draw.rounded_rectangle((42, 44, 50, 376), radius=4, fill=(*_ACCENT, 255))
    _paste_avatar(image, avatar_bytes, name)

    if kind == "level":
        label = "NIVEAU SUPÉRIEUR"
        title = name
        current_level = max(1, int(level or 1))
        subtitle = f"Bravo, tu viens de passer au niveau {current_level}."
        badge = f"NIVEAU {current_level}"
        filename = "sentrix_level_up.png"
    elif kind == "goodbye":
        label = "DÉPART"
        title = name
        subtitle = f"a quitté {server}."
        badge = f"{count} MEMBRE{'S' if count != 1 else ''}"
        filename = "sentrix_goodbye.png"
    else:
        label = "BIENVENUE"
        title = name
        subtitle = f"vient de rejoindre {server}."
        badge = f"{count} MEMBRE{'S' if count != 1 else ''}"
        filename = "sentrix_welcome.png"

    draw.text((350, 92), label, font=_font(21, bold=True), fill=(*_ACCENT, 255))
    title_text, title_font = _fit_text(draw, title, 720, 54, 32)
    draw.text((350, 128), title_text, font=title_font, fill=_TEXT)

    subtitle_font = _font(27)
    subtitle_text = subtitle
    if draw.textbbox((0, 0), subtitle_text, font=subtitle_font)[2] > 720:
        subtitle_text, subtitle_font = _fit_text(draw, subtitle_text, 720, 27, 22)
    draw.text((350, 205), subtitle_text, font=subtitle_font, fill=(218, 220, 226))

    badge_font = _font(19, bold=True)
    badge_box = draw.textbbox((0, 0), badge, font=badge_font)
    badge_w = badge_box[2] - badge_box[0] + 36
    draw.rounded_rectangle(
        (350, 263, 350 + badge_w, 310),
        radius=18,
        fill=(*_ACCENT, 46),
        outline=(*_ACCENT, 150),
        width=2,
    )
    draw.text((368, 274), badge, font=badge_font, fill=(232, 230, 255))

    footer = f"SentriX  •  {server}"
    footer_text, footer_font = _fit_text(draw, footer, 720, 19, 16)
    draw.text((350, 332), footer_text, font=footer_font, fill=_MUTED)

    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return discord.File(output, filename=filename)


__all__ = [
    "build_member_event_card",
    "fetch_background_image",
    "read_member_avatar",
]
