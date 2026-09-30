"""Expérience visuelle V5 de SentriX.

Ce module regroupe les thèmes, micro-interactions et cartes raster. Il ne contient
aucune donnée métier : les valeurs affichées viennent toujours de la base existante.
"""
from __future__ import annotations
import logging

import config as _config

import asyncio
import io
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger("bot.visual-v5")


ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "sentrix"
CARD_BACKGROUND = ASSET_DIR / "card-background-v5.png"

THEME_PRESETS: dict[str, dict[str, Any]] = {
    "sentrix": {
        "label": "SentriX Violet",
        "description": "Violet, indigo et cyan — identité officielle.",
        # Ce preset s'annonce comme l'identite officielle : il doit donc porter la
        # palette officielle, pas une variante figee avant son unification.
        "primary_color": int(_config.COLOR_BRAND),
        "secondary_color": 0x4C7DFF,
        "success_color": int(_config.COLOR_SUCCESS),
        "warning_color": int(_config.COLOR_WARNING),
        "danger_color": int(_config.COLOR_ERROR),
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
    # Plusieurs emplacements, parce que les deux d'origine n'existent que sur
    # l'image Debian de Railway. Ailleurs — une machine de développement, une
    # image plus légère — on retombait sur la police par défaut de Pillow, qui
    # n'a ni « É » ni « • » : la carte affichait « ⊠conomie » et un carré à la
    # place du séparateur. Personne ne le voyait en production, et c'est
    # exactement le genre de défaut qui surgit le jour où l'image de base change.
    candidates = [
        # Debian / Ubuntu, dont l'image Railway.
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        # Arch / Alpine.
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/TTF/DejaVuSans.ttf",
        # macOS, pour que le rendu local corresponde à la production.
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    # load_default() SANS taille rend une police de taille fixe minuscule : la
    # carte entière s'affiche alors au même corps, quel que soit le 50, 28 ou 20
    # demandé, et les accents sortent en carrés. Ce n'est visible que si DejaVu
    # et Liberation manquent tous les deux — ce qui n'arrive pas sur l'image
    # Debian de Railway, mais rendrait chaque carte illisible le jour où ça
    # change, sans aucune erreur pour le signaler.
    try:
        return ImageFont.load_default(size)
    except TypeError:  # Pillow < 9.2 n'accepte pas de taille
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


def fond_de_carte(largeur: int, hauteur: int, accent: tuple[int, int, int],
                  secondaire: tuple[int, int, int]):
    """Fond de carte généré : un dégradé lisse aux couleurs du serveur.

    **Pourquoi générer plutôt que charger une image.** ``card-background-v5.png``
    pèse 786 Ko et ne se décode pas — mesuré le 29/09/2026 :
    ``OSError: unrecognized data stream contents``. La production tombait donc
    systématiquement dans le repli de secours, qui peignait cent bandes plates
    de douze pixels : quatre-vingts couleurs en tout, et des marches visibles à
    l'œil. Ce n'est pas un fond « trop chargé » que voyaient les membres, c'est
    un dégradé cassé.

    Un fond généré n'a aucun fichier à corrompre, pèse quelques kilo-octets une
    fois compressé, et prend les couleurs choisies par le serveur — donc la
    carte ressemble au serveur et pas à tous les autres.

    Le dessin est volontairement sobre : un dégradé diagonal, une lueur douce
    derrière l'avatar, rien d'autre. C'est la demande de Jayden — « un
    background mieux et simple ».
    """
    from PIL import Image, ImageDraw, ImageFilter

    # Fond NEUTRE, volontairement. Il était teinté par l'accent, ce qui donnait
    # avec les couleurs par défaut de SentriX un dégradé violet vers bleu — le
    # cliché visuel par excellence, et Jayden l'a dit : « une couleur simple,
    # pas IA ». Un fond qui voyage d'une teinte à une autre attire l'œil sur
    # lui-même au lieu de laisser lire ce qu'il porte.
    #
    # Ardoise très sombre, avec une variation de luminosité si faible qu'on ne
    # lit pas un dégradé mais une surface. L'accent ne sert plus qu'aux
    # éléments qui doivent ressortir : la barre de progression, l'anneau de
    # l'avatar, le liseré. Une seule couleur forte, et du calme autour.
    del accent, secondaire
    base = (14, 15, 18)
    haut = (32, 34, 40)

    # Dégradé PAR PIXEL sur la diagonale. Calculé sur une petite image puis
    # agrandi : Pillow interpole alors les valeurs intermédiaires, ce qui donne
    # un dégradé continu au lieu des paliers du repli précédent — et coûte
    # quelques milliers d'opérations au lieu d'un demi-million.
    petit = Image.new("RGB", (64, 64))
    pixels = petit.load()
    for y in range(64):
        for x in range(64):
            # 0 en bas à gauche, 1 en haut à droite.
            d = (x / 63 * 0.72) + ((63 - y) / 63 * 0.28)
            pixels[x, y] = tuple(
                round(b + (h - b) * d) for b, h in zip(base, haut)
            )
    toile = petit.resize((largeur, hauteur), Image.Resampling.BICUBIC).convert("RGBA")

    # Une lueur BLANCHE et très discrète derrière l'avatar, pas une lueur
    # colorée : elle donne un peu de relief sans réintroduire la teinte qu'on
    # vient d'enlever. Floutée largement pour qu'aucun contour ne se voie.
    lueur = Image.new("RGBA", (largeur, hauteur), (0, 0, 0, 0))
    rayon = int(hauteur * 0.62)
    centre = (int(largeur * 0.16), hauteur // 2)
    ImageDraw.Draw(lueur).ellipse(
        (centre[0] - rayon, centre[1] - rayon, centre[0] + rayon, centre[1] + rayon),
        fill=(255, 255, 255, 14),
    )
    lueur = lueur.filter(ImageFilter.GaussianBlur(rayon // 2))
    return Image.alpha_composite(toile, lueur)


def _render_card_sync(
    avatar_bytes: bytes,
    display_name: str,
    guild_name: str,
    stats: dict[str, Any],
    settings: dict[str, Any],
    level_up: int | None,
    show_levels: bool,
    show_economy: bool,
) -> io.BytesIO:
    # Défauts NEUTRES. Ils valaient 0x6C5CE7 (violet) et 0x4C7DFF (bleu) : le
    # dégradé violet-vers-bleu, c'est-à-dire exactement le cliché que Jayden a
    # demandé de retirer — « une couleur simple, pas IA ».
    #
    # Un serveur qui choisit ses couleurs dans le dashboard les garde : ces
    # valeurs ne s'appliquent qu'à ceux qui n'ont rien réglé, et c'est le cas de
    # l'immense majorité. Gris clair pour la structure, ardoise claire pour
    # l'anneau : la carte se lit sans qu'aucune couleur ne réclame l'attention.
    accent = _hex_rgb(int(settings.get("primary_color", 0xE6E8EC)))
    secondary = _hex_rgb(int(settings.get("secondary_color", 0x8A8F99)))

    # Une montée de niveau ne réutilise plus toute la carte de profil. Le résultat
    # demandé est volontairement neutre : fond sombre uni, petite phrase, rien d'autre.
    if level_up is not None:
        canvas = Image.new("RGBA", (1200, 280), (24, 25, 28, 255))
        draw = ImageDraw.Draw(canvas, "RGBA")
        draw.rounded_rectangle(
            (24, 24, 1176, 256),
            radius=24,
            fill=(31, 32, 36, 255),
            outline=(62, 64, 71, 255),
            width=2,
        )
        text = f"Bravo {display_name}, tu es passé niveau {int(level_up)}"
        font = _font(34, bold=True)
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(
            ((1200 - (box[2] - box[0])) / 2, 122),
            text,
            font=font,
            fill=(238, 239, 242, 255),
        )
        output = io.BytesIO()
        canvas.convert("RGB").save(output, format="PNG", optimize=True)
        output.seek(0)
        return output

    # Fond généré, plus d'image à charger : l'asset card-background-v5.png ne se
    # décodait pas et la production peignait donc toujours le repli en bandes.
    # Voir fond_de_carte() pour le détail de la mesure.
    canvas = fond_de_carte(1200, 400, accent, secondary)
    draw = ImageDraw.Draw(canvas, "RGBA")
    # Opacité 96 et non 150 : à 150 le panneau masquait le dégradé sur 92 % de
    # la carte, et soigner le fond n'aurait servi à rien. Le texte reste sur un
    # fond sombre, donc lisible.
    draw.rounded_rectangle((34, 32, 1166, 368), radius=34, fill=(10, 11, 14, 120), outline=(*accent, 210), width=3)
    if show_levels:
        draw.rounded_rectangle((315, 286, 1110, 320), radius=17, fill=(24, 26, 31, 220))

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
    draw.text((340, 75), title, font=title_font, fill=(245, 246, 248, 255))
    label = "NOUVEAU NIVEAU" if level_up is not None else "PROFIL SENTRIX"
    draw.text((342, 45), label, font=_font(20, bold=True), fill=(*secondary, 255))
    if show_levels:
        draw.text((342, 143), f"Niveau {level}  •  Rang {rank}", font=_font(28, bold=True), fill=(214, 216, 222, 255))
    else:
        draw.text((342, 143), "Profil membre", font=_font(28, bold=True), fill=(214, 216, 222, 255))
    draw.text((342, 196), f"{guild_name}", font=_font(21), fill=(150, 154, 163, 255))

    if show_levels:
        bar_left, bar_top, bar_right, bar_bottom = 340, 286, 1110, 320
        progress_right = bar_left + round((bar_right - bar_left) * ratio)
        if progress_right > bar_left:
            draw.rounded_rectangle((bar_left, bar_top, progress_right, bar_bottom), radius=17, fill=(*accent, 245))
        draw.text((342, 332), f"{current_xp:,} / {required_xp:,} XP".replace(",", " "), font=_font(20, bold=True), fill=(228, 230, 235, 255))
        message_x = 620
        economy_x = 910
    else:
        message_x = 342
        economy_x = 700

    draw.text((message_x, 332), f"Messages  {int(stats.get('message_count', 0) or 0):,}".replace(",", " "), font=_font(20), fill=(168, 172, 181, 255))
    if show_economy:
        draw.text((economy_x, 332), f"Économie  {int(stats.get('total_money', 0) or 0):,}".replace(",", " "), font=_font(20), fill=(168, 172, 181, 255))

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
    show_levels: bool = True,
    show_economy: bool = True,
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
        logger.warning("Étape non critique ignorée dans render_member_card", exc_info=True)

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
            show_levels,
            show_economy,
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
            show_levels,
            show_economy,
        )
