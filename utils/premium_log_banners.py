"""Grandes bannières dédiées aux logs, sans changer les bandeaux des commandes.

Les informations personnelles restent dans les composants Discord pour être
accessibles, sélectionnables et correctes même si l'avatar change.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from utils.log_banners import COLORS, LOGO_PATH, ROOT
from utils.log_categories import canonical_event_type, resolve

logger = logging.getLogger("bot.premium-log-banners")
BANNER_DIR = ROOT / "assets" / "premium_log_banners"
SIZE = (1024, 232)
VERSION = 1

TITLES = {
    "member_ban": "BANNISSEMENT",
    "member_unban": "DÉBANNISSEMENT",
    "member_kick": "EXPULSION",
    "member_warn": "AVERTISSEMENT",
    "member_timeout": "TIMEOUT",
    "member_untimeout": "FIN DE TIMEOUT",
    "member_join": "NOUVEAU MEMBRE",
    "member_leave": "DÉPART D'UN MEMBRE",
    "role_add": "RÔLE AJOUTÉ",
    "role_remove": "RÔLE RETIRÉ",
    "role_update": "RÔLE MODIFIÉ",
    "role_create": "RÔLE CRÉÉ",
    "role_delete": "RÔLE SUPPRIMÉ",
    "message_delete": "MESSAGE SUPPRIMÉ",
    "message_edit": "MESSAGE MODIFIÉ",
    "message_bulk": "MESSAGES SUPPRIMÉS",
    "channel_create": "SALON CRÉÉ",
    "channel_delete": "SALON SUPPRIMÉ",
    "channel_update": "SALON MODIFIÉ",
}
CATEGORIES = {
    "moderation": "MODÉRATION",
    "members": "MEMBRES",
    "messages": "MESSAGES",
    "roles": "RÔLES",
    "channels": "SALONS",
    "voice": "VOCAL",
    "automod": "SÉCURITÉ",
    "tickets": "TICKETS",
}

_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)


def _font(size: int) -> ImageFont.ImageFont:
    for path in _FONT_PATHS:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def build_premium_banner(log_type: str) -> Image.Image:
    event_type = canonical_event_type(log_type)
    category, _emoji, kind = resolve(event_type)
    accent = COLORS.get(kind, (148, 117, 245))
    if event_type == "member_leave":
        accent = (247, 160, 93)
    if event_type.startswith("role_"):
        accent = (97, 156, 255)

    width, height = SIZE
    img = Image.new("RGB", SIZE)
    pix = img.load()
    for y in range(height):
        for x in range(width):
            glow = max(0.0, 1.0 - ((x - width * 0.86) / (width * 0.55)) ** 2
                       - ((y - height * 0.45) / (height * 1.4)) ** 2)
            strength = glow * 0.26 + (1.0 - y / height) * 0.09
            pix[x, y] = (
                min(255, int(12 + accent[0] * strength)),
                min(255, int(16 + accent[1] * strength)),
                min(255, int(29 + accent[2] * strength)),
            )

    art = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    d = ImageDraw.Draw(art)
    for i in range(7):
        x = 640 + i * 75
        d.line((x, -40, x - 205, 260), fill=(*accent, 16 + (i % 3) * 7), width=16)
    for i in range(32):
        x = 610 + ((i * 71 + 43) % 400)
        y = 12 + ((i * 53 + 17) % 202)
        r = 1 + i % 2
        d.ellipse((x - r, y - r, x + r, y + r), fill=(*accent, 80 + (i % 3) * 30))
    halo = art.filter(ImageFilter.GaussianBlur(12))
    img = Image.alpha_composite(img.convert("RGBA"), halo)
    img = Image.alpha_composite(img, art)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((25, 27, 35, 205), radius=5, fill=(*accent, 255))
    d.text((64, 36), "SENTRIX   /   JOURNAL DU SERVEUR", fill=(186, 195, 214), font=_font(20))
    title = TITLES.get(event_type, CATEGORIES.get(category, "ÉVÉNEMENT"))
    if len(title) > 24:
        title = title[:24]
    d.text((62, 81), title, fill=(252, 253, 255), font=_font(43))
    d.text((64, 156), CATEGORIES.get(category, "ÉVÉNEMENTS") + "  •  HISTORIQUE DISPONIBLE",
           fill=(*accent, 255), font=_font(19))
    d.line((64, 201, 960, 201), fill=(*accent, 76), width=2)

    if LOGO_PATH.is_file():
        try:
            with Image.open(LOGO_PATH) as logo:
                logo = logo.convert("RGBA")
                logo.thumbnail((105, 105), Image.Resampling.LANCZOS)
                x = 880 - logo.width // 2
                y = 112 - logo.height // 2
                img.alpha_composite(logo, dest=(x, y))
        except (OSError, ValueError):
            logger.warning("Logo SentriX ignoré pour la bannière premium", exc_info=True)
    return img.convert("RGB")


def get_premium_log_banner(log_type: str, title: str = "") -> Path:
    event_type = canonical_event_type(log_type, title)
    digest = hashlib.sha256(event_type.encode("utf-8")).hexdigest()[:12]
    path = BANNER_DIR / f"premium_{VERSION}_{digest}.webp"
    if path.is_file():
        return path
    BANNER_DIR.mkdir(parents=True, exist_ok=True)
    image = build_premium_banner(event_type)
    tmp = path.with_suffix(".tmp")
    image.save(tmp, format="WEBP", quality=85, method=5)
    tmp.replace(path)
    return path


__all__ = ["build_premium_banner", "get_premium_log_banner", "SIZE", "TITLES"]
