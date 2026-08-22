"""Expérience visuelle V5 de SentriX.

Ce module regroupe les thèmes, micro-interactions et cartes raster. Il ne contient
aucune donnée métier : les valeurs affichées viennent toujours de la base existante.
"""
from __future__ import annotations

import asyncio
import io
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps


ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "sentrix"
CARD_BACKGROUND = ASSET_DIR / "card-background-v5.png"

THEME_PRESETS: dict[str, dict[str, Any]] = {
    "sentrix": {
        "label": "SentriX Violet",
        "description": "Violet, indigo et cyan — identité officielle.",
        "primary_color": 0x6C5CE7,
        "secondary_color": 0x4C7DFF,
        "success_color": 0x2FBF71,
        "warning_color": 0xF0B232,
        "danger_color": 0xED4245,
    },
    "cyber": {
        "label": "Bleu Cyber",
        "description": "Bleu électrique, cyan et contraste technologique.",
        "primary_color": 0x2388FF,
        "secondary_color": 0x00B8D9,
        "success_color": 0x27C499,
        "warning_color": 0xF4B942,
        "danger_color": 0xF05252,
    },
    "noir": {
        "label": "Noir Premium",
        "description": "Anthracite, or discret et présentation luxueuse.",
        "primary_color": 0x2C2F3A,
        "secondary_color": 0xD6A94A,
        "success_color": 0x3FB984,
        "warning_color": 0xD6A94A,
        "danger_color": 0xD95763,
    },
}

THEME_ALIASES = {
    "violet": "sentrix",
    "officiel": "sentrix",
    "blue": "cyber",
    "bleu": "cyber",
    "black": "noir",
    "premium": "noir",
}


def resolve_theme(value: str | None) -> str | None:
    key = str(value or "").strip().casefold()
    key = THEME_ALIASES.get(key, key)
    return key if key in THEME_PRESETS else None


def theme_settings(name: str, *, compact_mode: bool | None = None) -> dict[str, Any]:
    key = resolve_theme(name) or "sentrix"
    settings = dict(THEME_PRESETS[key])
    settings.pop("label", None)
    settings.pop("description", None)
    settings["theme_preset"] = key
    if compact_mode is not None:
        settings["compact_mode"] = bool(compact_mode)
    return settings


def greeting(now: datetime | None = None) -> str:
    hour = (now or datetime.now()).hour
    if 5 <= hour < 12:
        return "Bonjour"
    if 12 <= hour < 18:
        return "Bon après-midi"
    return "Bonsoir"


def breadcrumb(*parts: Any) -> str:
    return " • ".join(str(part).strip() for part in parts if str(part or "").strip())


def error_reference() -> str:
    return f"SX-{secrets.token_hex(3).upper()}"


def seasonal_accent(base: int, now: datetime | None = None) -> int:
    """Accent saisonnier discret, sans changer les couleurs succès/erreur."""
    current = now or datetime.now()
    if current.month == 10 and current.day >= 24:
        return 0xD9772B
    if current.month == 12 and 15 <= current.day <= 27:
        return 0xC23B55
    if current.month == 1 and current.day <= 7:
        return 0x4C7DFF
    return int(base)


def _font(size: int, *, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, size: int, *, bold: bool = False):
    value = str(text or "")
    font = _font(size, bold=bold)
    while value and draw.textbbox((0, 0), value, font=font)[2] > max_width:
        value = value[:-1].rstrip()
    if value != str(text or ""):
        value = value[:-1].rstrip() + "…" if len(value) > 1 else "…"
    return value, font


def _hex_rgb(value: int) -> tuple[int, int, int]:
    return ((value >> 16) & 255, (value >> 8) & 255, value & 255)


def _render_card_sync(
    avatar_bytes: bytes,
    display_name: str,
    guild_name: str,
    stats: dict[str, Any],
    settings: dict[str, Any],
    level_up: int | None,
) -> io.BytesIO:
    try:
        background = Image.open(CARD_BACKGROUND).convert("RGBA")
        canvas = ImageOps.fit(background, (1200, 400), method=Image.Resampling.LANCZOS)
    except (OSError, ValueError):
        # Dernier filet de sécurité si l'asset est absent ou corrompu sur l'hébergeur.
        canvas = Image.new("RGBA", (1200, 400), (10, 13, 42, 255))
        backdrop = ImageDraw.Draw(canvas, "RGBA")
        for x in range(0, 1200, 12):
            ratio = x / 1200
            backdrop.rectangle(
                (x, 0, x + 12, 400),
                fill=(35 + round(50 * ratio), 28, 105 + round(65 * ratio), 255),
            )
    overlay = Image.new("RGBA", canvas.size, (4, 8, 28, 30))
    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas, "RGBA")

    accent = _hex_rgb(int(settings.get("primary_color", 0x6C5CE7)))
    secondary = _hex_rgb(int(settings.get("secondary_color", 0x4C7DFF)))
    draw.rounded_rectangle((34, 32, 1166, 368), radius=34, fill=(6, 10, 36, 150), outline=(*accent, 210), width=3)
    draw.rounded_rectangle((315, 286, 1110, 320), radius=17, fill=(15, 20, 55, 210))

    avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
    avatar = ImageOps.fit(avatar, (222, 222), method=Image.Resampling.LANCZOS)
    mask = Image.new("L", (222, 222), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 221, 221), fill=255)
    ring = Image.new("RGBA", (242, 242), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((2, 2, 239, 239), outline=(*secondary, 255), width=7)
    canvas.alpha_composite(ring, (68, 79))
    canvas.paste(avatar, (78, 89), mask)

    level = int(level_up if level_up is not None else stats.get("current_level", 0) or 0)
    current_xp = int(stats.get("current_level_xp", 0) or 0)
    required_xp = max(1, int(stats.get("required_xp", 1) or 1))
    ratio = max(0.0, min(current_xp / required_xp, 1.0))
    rank = f"#{stats.get('rank')}" if stats.get("is_ranked") and stats.get("rank") else "Non classé"

    title, title_font = _fit_text(draw, display_name, 700, 50, bold=True)
    draw.text((340, 75), title, font=title_font, fill=(250, 251, 255, 255))
    label = "NOUVEAU NIVEAU" if level_up is not None else "PROFIL SENTRIX"
    draw.text((342, 45), label, font=_font(20, bold=True), fill=(*secondary, 255))
    draw.text((342, 143), f"Niveau {level}  •  Rang {rank}", font=_font(28, bold=True), fill=(213, 222, 255, 255))
    draw.text((342, 196), f"{guild_name}", font=_font(21), fill=(170, 181, 220, 255))

    bar_left, bar_top, bar_right, bar_bottom = 340, 286, 1110, 320
    progress_right = bar_left + round((bar_right - bar_left) * ratio)
    if progress_right > bar_left:
        draw.rounded_rectangle((bar_left, bar_top, progress_right, bar_bottom), radius=17, fill=(*accent, 245))
    draw.text((342, 332), f"{current_xp:,} / {required_xp:,} XP".replace(",", " "), font=_font(20, bold=True), fill=(235, 238, 255, 255))
    draw.text((620, 332), f"Messages  {int(stats.get('message_count', 0) or 0):,}".replace(",", " "), font=_font(20), fill=(194, 203, 235, 255))
    draw.text((910, 332), f"Économie  {int(stats.get('total_money', 0) or 0):,}".replace(",", " "), font=_font(20), fill=(194, 203, 235, 255))

    output = io.BytesIO()
    canvas.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return output


async def render_member_card(
    member,
    guild,
    stats: dict[str, Any],
    settings: dict[str, Any],
    *,
    level_up: int | None = None,
) -> io.BytesIO:
    # On demande au CDN Discord une vraie version PNG de la PP. ``format='png'`` est
    # important : pour une PP animée, ``static_format='png'`` conservait encore le GIF,
    # puis certains GIF optimisés faisaient échouer Pillow et déclenchaient l'icône de
    # secours. Le PNG correspond à la vraie première image de la PP animée.
    avatar = getattr(member, "avatar", None) or member.display_avatar
    try:
        static_avatar = avatar.replace(format="png", size=256)
    except (TypeError, ValueError):
        static_avatar = avatar
    avatar_bytes: bytes | None = None
    try:
        avatar_bytes = await asyncio.wait_for(static_avatar.read(), timeout=4)
    except Exception:
        pass

    if not avatar_bytes:
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            headers = {"User-Agent": "SentriX Discord Bot/5.0"}
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(str(static_avatar.url)) as response:
                    response.raise_for_status()
                    avatar_bytes = await response.read()
        except Exception:
            avatar_bytes = None

    if not avatar_bytes:
        display_avatar = member.display_avatar
        if display_avatar is not None and display_avatar != avatar:
            try:
                display_static = display_avatar.replace(format="png", size=256)
                avatar_bytes = await asyncio.wait_for(display_static.read(), timeout=3)
            except Exception:
                avatar_bytes = None

    if not avatar_bytes:
        avatar_bytes = await asyncio.to_thread((ASSET_DIR / "profile.png").read_bytes)
    try:
        return await asyncio.to_thread(
            _render_card_sync,
            avatar_bytes,
            member.display_name,
            guild.name,
            stats or {},
            settings or theme_settings("sentrix"),
            level_up,
        )
    except Exception:
        # Une donnée de profil exotique ou un avatar illisible ne doit jamais condamner
        # toute la commande : on fabrique une carte SentriX neutre au second essai.
        fallback_avatar = await asyncio.to_thread((ASSET_DIR / "profile.png").read_bytes)
        fallback_stats = {
            "current_level": 0,
            "current_level_xp": 0,
            "required_xp": 100,
            "rank": None,
            "is_ranked": False,
            "message_count": 0,
            "total_money": 0,
        }
        return await asyncio.to_thread(
            _render_card_sync,
            fallback_avatar,
            str(getattr(member, "display_name", "Membre"))[:40],
            str(getattr(guild, "name", "Serveur"))[:60],
            fallback_stats,
            theme_settings("sentrix"),
            level_up,
        )
