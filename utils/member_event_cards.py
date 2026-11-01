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
_TEXT = (250, 250, 252)
_MUTED = (210, 212, 217)
_BG = (43, 45, 49)
_BG_DARK = (35, 36, 40)
_BORDER = (74, 76, 82)

EVENT_BACKGROUND_PRESETS = {
    # 30/10/2026 (Jayden : « niveau et bienvenue n'ont pas de bannière ») :
    # fond SentriX par défaut, dégradé violet de la bannière du bot.
    "preset:sentrix": ((15, 12, 44), (24, 18, 70)),
    "preset:dark": ((28, 29, 33), (39, 40, 45)),
    "preset:gray": ((43, 45, 49), (52, 54, 60)),
    "preset:light": ((66, 68, 75), (78, 80, 88)),
}


#: Chemins essayés dans l'ordre. Seuls deux existaient, tous deux Linux : sur
#: tout hôte sans DejaVu — un Mac de développement, une image de base
#: différente — la carte entière retombait sur la police bitmap par défaut et
#: TOUT le texte sortait minuscule, quelle que soit la taille demandée.
_FONTES = {
    False: (
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ),
    True: (
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Black.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ),
}


def _font(size: int, *, bold: bool = False):
    for name in _FONTES[bool(bold)]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    # La TAILLE compte aussi dans le repli : `load_default()` sans argument rend
    # une police bitmap minuscule, et c'est ce qui aplatissait toute la
    # hiérarchie de la carte — titre et sous-titre sortaient identiques.
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow trop ancien pour la taille
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


DEFAULT_PRESET = "preset:sentrix"


def _preset_palette(preset: str | None):
    return EVENT_BACKGROUND_PRESETS.get(str(preset or ""), EVENT_BACKGROUND_PRESETS[DEFAULT_PRESET])


def _fond_sentrix() -> Image.Image:
    """Dégradé indigo → violet, trame de points et halo : l'identité de la bannière."""
    w, h = _SIZE
    c1, c2, c3 = (15, 12, 44), (48, 30, 132), (96, 66, 220)
    fond = Image.new("RGB", (w, 1))
    for x in range(w):
        a = x / max(1, w - 1)
        if a < 0.5:
            k = a / 0.5
            c = tuple(int(c1[i] + (c2[i] - c1[i]) * k) for i in range(3))
        else:
            k = (a - 0.5) / 0.5
            c = tuple(int(c2[i] + (c3[i] - c2[i]) * k) for i in range(3))
        fond.putpixel((x, 0), c)
    image = fond.resize((w, h)).convert("RGBA")
    calque = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    trace = ImageDraw.Draw(calque)
    for x in range(12, w, 26):
        for y in range(12, h, 26):
            trace.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(255, 255, 255, 18))
    halo = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse((w - 520, -160, w + 120, h + 120), fill=(150, 120, 255, 80))
    from PIL import ImageFilter

    halo = halo.filter(ImageFilter.GaussianBlur(90))
    return Image.alpha_composite(Image.alpha_composite(image, calque), halo)


#: Filet d'accent par type de carte.
_FILETS = {"welcome": (170, 150, 255), "level": (255, 196, 76), "goodbye": (150, 160, 190)}


def _neutral_background(
    custom_bytes: bytes | None = None,
    preset: str | None = None,
) -> Image.Image:
    """Fond plat SentriX. Les utilisateurs choisissent uniquement parmi 3 presets."""
    if custom_bytes:
        # Conservé uniquement pour compatibilité interne ; le dashboard et +setup
        # n'acceptent plus d'URL ou d'image personnalisée.
        try:
            source = Image.open(io.BytesIO(custom_bytes)).convert("RGB")
            image = ImageOps.fit(source, _SIZE, method=Image.Resampling.LANCZOS).convert("RGBA")
            shade = Image.new("RGBA", _SIZE, (0, 0, 0, 95))
            return Image.alpha_composite(image, shade)
        except Exception:
            pass
    if str(preset or DEFAULT_PRESET) not in EVENT_BACKGROUND_PRESETS or str(preset or DEFAULT_PRESET) == DEFAULT_PRESET:
        return _fond_sentrix()
    canvas, _panel = _preset_palette(preset)
    return Image.new("RGBA", _SIZE, (*canvas, 255))


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
        outline=(108, 110, 116, 255),
        width=5,
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
    background_preset: str | None = None,
    avatar_bytes: bytes | None = None,
    level: int | None = None,
    language: str = "fr",
) -> discord.File:
    """Carte sobre façon Discord : avatar rond, gros titre, zéro couleur néon."""
    kind = str(kind or "welcome").casefold()
    image = _neutral_background(background_bytes, background_preset)
    draw = ImageDraw.Draw(image, "RGBA")
    _canvas, panel_color = _preset_palette(background_preset)

    name = str(
        getattr(member, "display_name", None)
        or getattr(member, "name", None)
        or "Membre"
    ).strip()
    guild = getattr(member, "guild", None)
    server = str(getattr(guild, "name", None) or "le serveur").strip()

    # Cadre simple, plat, identique pour les trois cartes.
    sentrix = background_bytes is None and str(background_preset or DEFAULT_PRESET) in (DEFAULT_PRESET, "") \
        or str(background_preset or "") not in EVENT_BACKGROUND_PRESETS
    # Calque à part : sur une image RGBA, ImageDraw REMPLACE les pixels au lieu
    # de les mélanger ; un panneau translucide sortait opaque.
    panneau = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(panneau).rounded_rectangle(
        (34, 38, 1166, 382),
        radius=24,
        fill=(10, 8, 34, 110) if sentrix and background_bytes is None
        else (*panel_color, 255) if background_bytes is None else (15, 16, 18, 145),
        outline=(255, 255, 255, 70) if sentrix else (*_BORDER, 255),
        width=2,
    )
    image.alpha_composite(panneau)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle((365, 86, 445, 92), radius=3, fill=(*_FILETS.get(kind, _FILETS["welcome"]), 255))
    _paste_avatar(image, avatar_bytes, name)

    x = 365
    # Le NOM est l'élément principal, et il n'était pas dessiné du tout : la
    # carte affichait « Bienvenue / sur le serveur Discord / Le Repaire » sans
    # jamais nommer la personne accueillie. Il ne servait qu'à l'initiale de
    # l'avatar. Une carte de bienvenue qui ne dit pas qui arrive ne fait rien.
    #
    # Trois niveaux, donc trois tailles : un libellé discret, le nom en grand,
    # le contexte en dessous. Avant, les trois lignes se valaient et la carte
    # n'avait aucune hiérarchie.
    english = str(language or "fr").casefold().startswith("en")
    if kind == "level":
        current_level = max(1, int(level or 1))
        libelle = "Level reached" if english else "Niveau atteint"
        vedette = f"Level {current_level}" if english else f"Niveau {current_level}"
        detail = name
        filename = "sentrix_level_up.png"
    elif kind == "goodbye":
        libelle = "Goodbye" if english else "À bientôt"
        vedette = name
        detail = f"left {server}" if english else f"a quitté {server}"
        filename = "sentrix_goodbye.png"
    else:
        libelle = "Welcome" if english else "Bienvenue"
        vedette = name
        detail = f"joined {server}" if english else f"vient de rejoindre {server}"
        filename = "sentrix_welcome.png"

    libelle_text, libelle_font = _fit_text(draw, libelle, 760, 30, 22)
    draw.text((x, 104), libelle_text, font=libelle_font, fill=_MUTED)

    vedette_text, vedette_font = _fit_text(draw, vedette, 760, 66, 34)
    draw.text((x, 150), vedette_text, font=vedette_font, fill=_TEXT)

    detail_text, detail_font = _fit_text(draw, detail, 760, 32, 22)
    draw.text((x, 240), detail_text, font=detail_font, fill=_MUTED)

    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return discord.File(output, filename=filename)


__all__ = [
    "build_member_event_card",
    "EVENT_BACKGROUND_PRESETS",
    "fetch_background_image",
    "read_member_avatar",
]
