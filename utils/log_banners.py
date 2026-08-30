"""Bannières premium pour les journaux SentriX.

Les cinq bandes sont générées en mémoire avec Pillow (1024 px) puis jointes au message
Discord. Aucun fichier PNG statique ni URL externe n'est requis.

Palette :
- error   : erreur, suppression, départ, sanction forte ;
- success : restauration, unban, unmute, action réussie ;
- warning : avertissement, mute, permission/sécurité ;
- info    : modification et information courante ;
- special : arrivée et événement spécial.
"""
from __future__ import annotations

import io
import logging
import time
from functools import lru_cache

import discord

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:  # pragma: no cover - Pillow est une dépendance SentriX.
    Image = ImageDraw = ImageFilter = None

from utils import embeds as embeds_mod
from utils import log_service

logger = logging.getLogger("bot")

BANNER_WIDTH = 1024
BANNER_HEIGHT = 150
BANNER_BG = (7, 9, 15)

STYLE_PALETTE: dict[str, tuple[int, int, int]] = {
    "error": (255, 45, 45),
    "success": (45, 255, 136),
    "warning": (255, 181, 45),
    "info": (45, 154, 255),
    "special": (155, 77, 255),
}
STYLE_COLOURS = {
    name: (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]
    for name, rgb in STYLE_PALETTE.items()
}

_SPECIAL_WORDS = (
    "membre arrivé",
    "membre arrive",
    "arrivée",
    "arrivee",
    "bienvenue",
    "boost",
    "anniversaire",
    "événement spécial",
    "evenement special",
)
_SUCCESS_WORDS = (
    "débann",
    "debann",
    "unban",
    "unmute",
    "démute",
    "demute",
    "restaur",
    "réactiv",
    "reactiv",
    "succès",
    "succes",
    "réussi",
    "reussi",
)
_WARNING_WORDS = (
    "avert",
    "warn",
    "mute",
    "timeout",
    "permission",
    "vérification",
    "verification",
    "anti-spam",
    "antispam",
    "automod",
)
_ERROR_WORDS = (
    "supprim",
    "bann",
    "ban ",
    "kick",
    "expuls",
    "membre parti",
    "quitt",
    "erreur",
    "échec",
    "echec",
    "sanction",
    "nuke",
)


def resolve_log_style(log_type: str, embed: discord.Embed) -> str:
    """Retourne un des cinq styles à partir de l'action réellement journalisée."""
    title = str(embed.title or "").casefold()

    if any(word in title for word in _SPECIAL_WORDS):
        return "special"
    # Important : succès avant danger, car « débannissement » contient « bannissement ».
    if any(word in title for word in _SUCCESS_WORDS):
        return "success"
    # Important : avertissement avant le fallback modération rouge.
    if any(word in title for word in _WARNING_WORDS):
        return "warning"
    if any(word in title for word in _ERROR_WORDS):
        return "error"

    normalized_type = str(log_type or "").strip().casefold()
    if normalized_type == "moderation":
        return "error"
    if normalized_type == "automod":
        return "warning"
    if normalized_type == "members" and "arriv" in title:
        return "special"
    return "info"


@lru_cache(maxsize=len(STYLE_PALETTE))
def _banner_png(style: str) -> bytes:
    """Construit la bande 1024 px et met en cache les octets PNG."""
    if Image is None or ImageDraw is None or ImageFilter is None:
        return b""

    style = style if style in STYLE_PALETTE else "info"
    accent = STYLE_PALETTE[style]
    width, height = BANNER_WIDTH, BANNER_HEIGHT
    center_x = width // 2
    center_y = height // 2
    gap_half = 108

    base = Image.new("RGBA", (width, height), (*BANNER_BG, 255))
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow, "RGBA")

    # Deux faisceaux larges qui convergent vers le trou central.
    glow_draw.polygon(
        [(0, 11), (center_x - gap_half, 47), (center_x - gap_half, height - 47), (0, height - 11)],
        fill=(*accent, 175),
    )
    glow_draw.polygon(
        [(width, 11), (center_x + gap_half, 47), (center_x + gap_half, height - 47), (width, height - 11)],
        fill=(*accent, 175),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=22))
    base = Image.alpha_composite(base, glow)

    # Dégradé horizontal plus précis : fort aux extrémités, sombre près du centre.
    pixels = base.load()
    max_distance = max(1, center_x - gap_half)
    for x in range(width):
        distance_from_hole = abs(x - center_x) - gap_half
        if distance_from_hole <= 0:
            continue
        strength = min(1.0, distance_from_hole / max_distance) ** 0.62
        for y in range(height):
            vertical = 0.48 + 0.52 * (1.0 - abs(y - center_y) / max(1, center_y))
            mix = 0.58 * strength * vertical
            old = pixels[x, y]
            pixels[x, y] = (
                round(old[0] * (1 - mix) + accent[0] * mix),
                round(old[1] * (1 - mix) + accent[1] * mix),
                round(old[2] * (1 - mix) + accent[2] * mix),
                255,
            )

    draw = ImageDraw.Draw(base, "RGBA")

    # Rails lumineux haut/bas, comme une vraie bande de statut.
    for offset, alpha in ((0, 210), (1, 130), (2, 70)):
        draw.line(
            [(0, 8 + offset), (center_x - gap_half - 12, 41 + offset)],
            fill=(*accent, alpha),
            width=2,
        )
        draw.line(
            [(center_x + gap_half + 12, 41 + offset), (width, 8 + offset)],
            fill=(*accent, alpha),
            width=2,
        )
        draw.line(
            [(0, height - 9 - offset), (center_x - gap_half - 12, height - 42 - offset)],
            fill=(*accent, alpha),
            width=2,
        )
        draw.line(
            [(center_x + gap_half + 12, height - 42 - offset), (width, height - 9 - offset)],
            fill=(*accent, alpha),
            width=2,
        )

    # Trou central sombre, volontairement vide : il peut recevoir le logo SentriX plus tard.
    hole = [
        (center_x - 72, 16),
        (center_x + 72, 16),
        (center_x + 112, center_y),
        (center_x + 72, height - 16),
        (center_x - 72, height - 16),
        (center_x - 112, center_y),
    ]
    draw.polygon(hole, fill=(4, 5, 10, 255))
    draw.line(hole + [hole[0]], fill=(*accent, 70), width=2)

    # Assombrit les bords du trou pour que le centre reste propre même sans logo.
    inner = [
        (center_x - 58, 28),
        (center_x + 58, 28),
        (center_x + 91, center_y),
        (center_x + 58, height - 28),
        (center_x - 58, height - 28),
        (center_x - 91, center_y),
    ]
    draw.polygon(inner, fill=(6, 7, 12, 255))

    output = io.BytesIO()
    base.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


def make_banner_file(style: str) -> discord.File | None:
    png = _banner_png(style)
    if not png:
        return None
    safe_style = style if style in STYLE_PALETTE else "info"
    return discord.File(io.BytesIO(png), filename=f"banner_{safe_style}.png")


def _render_embed(log_type: str, source: discord.Embed) -> tuple[discord.Embed, str]:
    """Normalise le log puis applique la couleur correspondant à la bannière."""
    rendered = (
        source
        if getattr(getattr(source, "image", None), "url", None) == embeds_mod.SENTRIX_BANNER_URL
        else embeds_mod.normalize_log(source)
    )
    style = resolve_log_style(log_type, rendered)
    rendered.colour = discord.Colour(STYLE_COLOURS[style])
    return rendered, style


async def send_log_v81(
    bot,
    guild: discord.Guild,
    log_type: str,
    embed: discord.Embed,
    file: discord.File | None = None,
    *,
    view: discord.ui.View | None = None,
    event_key: str | None = None,
) -> bool:
    """Transport V81 : bannière 1024 px + couleur sémantique + zéro ping."""
    if not log_service.is_primary_process():
        logger.info(
            "Log volontairement désactivé par SENTRIX_LOG_PRODUCER guild=%s type=%s",
            guild.id,
            log_type,
        )
        return False

    rendered, style = _render_embed(log_type, embed)

    semantic_key = log_service.semantic_event_key(guild.id, log_type, rendered)
    if log_service._is_duplicate(event_key) or log_service._is_duplicate(semantic_key):
        logger.debug(
            "Log dupliqué ignoré guild=%s type=%s key=%s",
            guild.id,
            log_type,
            event_key or semantic_key,
        )
        return False

    try:
        setting = await log_service.get_log_setting(bot, guild.id, log_type)
    except Exception:
        logger.exception(
            "Impossible de lire/réparer la configuration du log %s sur %s.",
            log_type,
            guild.id,
        )
        return False

    if not setting["enabled"]:
        logger.info("Log désactivé guild=%s type=%s", guild.id, log_type)
        return False

    # Un transcript existant reste obligatoire s'il a été fourni. La bannière, elle,
    # se dégrade proprement si le salon n'autorise pas les pièces jointes.
    ok, reason = log_service.validate_channel(
        guild,
        setting["channel_id"],
        needs_file=file is not None,
    )
    if not ok:
        logger.warning(
            "Log %s non envoyé sur guild=%s : %s",
            log_type,
            guild.id,
            reason,
        )
        return False

    channel = guild.get_channel(setting["channel_id"])
    me = guild.me
    can_attach_banner = bool(
        me is not None and channel.permissions_for(me).attach_files
    )

    banner_file = make_banner_file(style) if can_attach_banner else None
    attachments: list[discord.File] = []
    if banner_file is not None:
        rendered.set_image(url=f"attachment://{banner_file.filename}")
        attachments.append(banner_file)
    else:
        # Évite de laisser l'ancienne URL de bannière si Attach Files est refusé.
        rendered.remove_image()

    if file is not None:
        attachments.append(file)

    kwargs = {
        "embed": rendered,
        "allowed_mentions": log_service.LOG_ALLOWED_MENTIONS,
    }
    if view is not None:
        kwargs["view"] = view
    if len(attachments) == 1:
        kwargs["file"] = attachments[0]
    elif attachments:
        kwargs["files"] = attachments

    try:
        await channel.send(**kwargs)
        logger.info(
            "Log V81 envoyé guild=%s type=%s style=%s channel=%s banner=%s",
            guild.id,
            log_type,
            style,
            channel.id,
            banner_file is not None,
        )
        return True
    except (discord.Forbidden, discord.HTTPException):
        logger.exception(
            "Échec d'envoi du log V81 %s dans %s.",
            log_type,
            setting["channel_id"],
        )
        return False


async def send_test_log_v81(
    bot,
    guild: discord.Guild,
    log_type: str,
    author: discord.abc.User,
) -> tuple[bool, str]:
    """Le bouton de test passe par exactement le même renderer que les vrais logs."""
    setting = await log_service.get_log_setting(bot, guild.id, log_type)
    if not setting["enabled"]:
        return False, "Ce type de log est désactivé. Activez-le avant le test."

    ok, reason = log_service.validate_channel(guild, setting["channel_id"])
    if not ok:
        return False, f"Impossible d'envoyer un test : {reason}."

    label = log_service.LOG_TYPES.get(log_type, {}).get("label", log_type)
    test_embed = embeds_mod.log_embed(
        f"Test de log — {label}",
        fields=(
            ("Catégorie", label, False),
            ("Déclenché par", f"<@{author.id}>", True),
        ),
        banner=False,
    )
    sent = await send_log_v81(
        bot,
        guild,
        log_type,
        test_embed,
        event_key=log_service.make_event_key(
            guild.id,
            "log_test",
            executor_id=author.id,
            discriminator=time.time_ns(),
        ),
    )
    channel = guild.get_channel(setting["channel_id"])
    if sent:
        return True, f"Test envoyé dans {channel.mention}."
    return False, "Le test n'a pas pu être envoyé dans le salon de logs."


def install() -> None:
    """Installe une seule fois le transport visuel V81 sur le logger canonique."""
    if getattr(log_service, "_sentrix_log_banners_v81", False):
        return
    log_service.send_log = send_log_v81
    log_service.send_test_log = send_test_log_v81
    log_service._sentrix_log_banners_v81 = True
