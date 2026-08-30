"""SentriX V82 — profil réellement compact et logs réellement larges.

Cette couche corrige deux limites visibles de V81 :
- un embed composé de nombreux champs restait très vertical après conversion Components V2 ;
- la bannière des logs dépendait d'une pièce jointe générée à la volée et disparaissait
  lorsque le salon n'autorisait pas Attach Files.

V82 garde la logique métier existante, mais remplace le rendu :
- le profil compact regroupe chaque section sur une seule ligne ;
- les logs utilisent toujours la grande bannière publique SentriX déjà versionnée dans
  ``assets/sentrix-log-header.png`` ;
- les champs inline des logs sont regroupés horizontalement pour forcer un rendu rectangle.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import discord
from discord.ext import commands

from utils import embeds, log_service
from . import premium_ui_v81 as v81

logger = logging.getLogger("bot.premium-ui-v82")
RUNTIME_MARKER = "Premium UI V82"
ACCENT = discord.Colour(0x6D5DFB)

_DECORATIVE_LINE_RE = re.compile(r"^[\s━─—_\-=•·|]{8,}$")


def _plain(value: object) -> str:
    return str(value or "").strip()


def _safe_text(value: object) -> str:
    text = _plain(value)
    return re.sub(r"@(everyone|here)\b", lambda m: "@\u200b" + m.group(1), text, flags=re.IGNORECASE)


def _clean_description(value: object) -> str:
    """Retire les longues barres décoratives qui gonflent inutilement le panneau."""
    lines: list[str] = []
    for raw in _safe_text(value).splitlines():
        line = raw.strip()
        if not line or _DECORATIVE_LINE_RE.fullmatch(line):
            continue
        lines.append(line)
    return "\n".join(lines)


def _compact_value(value: object) -> str:
    """Transforme un champ vertical label/valeur en une ligne lisible."""
    lines = [line.strip() for line in _safe_text(value).splitlines() if line.strip()]
    if not lines:
        return "—"
    if len(lines) == 1:
        return lines[0]

    # Cas fréquent des anciens profils : label, valeur, label, valeur...
    if len(lines) % 2 == 0:
        pairs: list[str] = []
        sensible = True
        for index in range(0, len(lines), 2):
            label = lines[index].strip("* _:`•-")
            val = lines[index + 1]
            if not label or len(label) > 48 or len(val) > 100:
                sensible = False
                break
            if not val.startswith("**") and not val.startswith("<"):
                val = f"**{val.strip('*')}**"
            pairs.append(f"{label} {val}")
        if sensible:
            return " · ".join(pairs)

    # Les listes courtes sont aplaties ; les textes longs restent lisibles sur plusieurs lignes.
    if len(lines) <= 6 and all(len(line) <= 120 for line in lines):
        return " · ".join(line.lstrip("•- ") for line in lines)
    return "\n".join(lines)


def _compact_field_rows(embed: discord.Embed) -> list[str]:
    rows: list[str] = []
    for field in embed.fields:
        name = _safe_text(field.name)
        value = _compact_value(field.value)
        if not name or not value:
            continue
        rows.append(f"**{name}** — {value}")
    return rows


def _clone_button(item: discord.ui.Button) -> discord.ui.Button | None:
    try:
        kwargs: dict[str, Any] = {
            "style": item.style,
            "label": item.label,
            "disabled": item.disabled,
            "emoji": item.emoji,
        }
        if item.style is discord.ButtonStyle.link:
            kwargs["url"] = item.url
        elif getattr(item, "sku_id", None):
            kwargs["sku_id"] = item.sku_id
        else:
            kwargs["custom_id"] = item.custom_id
        clone = discord.ui.Button(**kwargs)
        if item.style is not discord.ButtonStyle.link and not getattr(item, "sku_id", None):
            clone.callback = item.callback
        return clone
    except Exception:
        logger.debug("V82: bouton legacy impossible à recopier", exc_info=True)
        return None


def _append_buttons(container: discord.ui.Container, legacy_view: discord.ui.View | None) -> None:
    if legacy_view is None:
        return
    buttons: list[discord.ui.Button] = []
    for item in getattr(legacy_view, "children", ()):
        if isinstance(item, discord.ui.Button):
            clone = _clone_button(item)
            if clone is not None:
                buttons.append(clone)
    if not buttons:
        return
    container.add_item(discord.ui.Separator())
    for index in range(0, len(buttons), 5):
        container.add_item(discord.ui.ActionRow(*buttons[index:index + 5]))


class PremiumEmbedViewV82(discord.ui.LayoutView):
    """Version compacte de V81, particulièrement adaptée à +profile/+serverinfo."""

    def __init__(
        self,
        embed: discord.Embed,
        *,
        compact: bool = False,
        legacy_view: discord.ui.View | None = None,
        title_override: str | None = None,
    ):
        super().__init__(timeout=getattr(legacy_view, "timeout", 300) if legacy_view is not None else 300)
        container = discord.ui.Container(accent_colour=ACCENT)
        title = _safe_text(title_override or embed.title or "SentriX")
        description = _clean_description(embed.description)
        thumbnail = _plain(getattr(embed.thumbnail, "url", None))

        # ## au lieu de # : le titre reste net sans prendre une hauteur excessive.
        header = f"## {title}"
        if description:
            header += f"\n{description[:700]}"

        if thumbnail:
            container.add_item(
                discord.ui.Section(
                    discord.ui.TextDisplay(header),
                    accessory=discord.ui.Thumbnail(thumbnail, description="Profil"),
                )
            )
        else:
            container.add_item(discord.ui.TextDisplay(header))

        if embed.fields:
            container.add_item(discord.ui.Separator())
            if compact:
                # Une seule zone texte : 4 sections deviennent 4 lignes au lieu de 20+ lignes.
                rows = _compact_field_rows(embed)
                if rows:
                    body = "\n".join(rows)
                    container.add_item(discord.ui.TextDisplay(body[:3900]))
            else:
                for field in embed.fields:
                    name = _safe_text(field.name)
                    value = _safe_text(field.value)
                    if name and value:
                        container.add_item(discord.ui.TextDisplay(f"**{name}**\n{value}"[:3900]))

        # En compact, le footer purement décoratif n'ajoute pas une ligne supplémentaire.
        if not compact:
            footer = _plain(getattr(embed.footer, "text", None))
            if footer:
                container.add_item(discord.ui.Separator())
                container.add_item(discord.ui.TextDisplay(f"-# {_safe_text(footer)[:500]}"))

        _append_buttons(container, legacy_view)
        self.add_item(container)


def _log_field_body(embed: discord.Embed) -> str:
    """Regroupe les champs inline par trois pour rendre le log horizontal et large."""
    blocks: list[str] = []
    inline: list[str] = []

    def flush_inline() -> None:
        nonlocal inline
        if inline:
            blocks.append("　　".join(inline))
            inline = []

    for field in embed.fields:
        name = _safe_text(field.name)
        value = _safe_text(field.value)
        if not name or not value:
            continue
        value = _compact_value(value)
        item = f"**{name}** {value}"
        if field.inline and len(item) <= 220 and "\n" not in item:
            inline.append(item)
            if len(inline) == 3:
                flush_inline()
        else:
            flush_inline()
            blocks.append(f"**{name}**\n{value}")
    flush_inline()
    return "\n\n".join(blocks)


class PremiumLogViewV82(discord.ui.LayoutView):
    def __init__(
        self,
        embed: discord.Embed,
        *,
        banner_url: str,
        legacy_view: discord.ui.View | None,
    ):
        super().__init__(timeout=getattr(legacy_view, "timeout", 300) if legacy_view is not None else 300)
        container = discord.ui.Container()

        # URL publique GitHub : visible même sans permission Attach Files dans le salon.
        gallery = discord.ui.MediaGallery()
        gallery.add_item(media=banner_url, description="Bannière SentriX")
        container.add_item(gallery)

        title = _safe_text(embed.title or "Journal SentriX")
        thumbnail = _plain(getattr(embed.thumbnail, "url", None))
        if thumbnail:
            container.add_item(
                discord.ui.Section(
                    discord.ui.TextDisplay(f"## {title}"),
                    accessory=discord.ui.Thumbnail(thumbnail, description="SentriX"),
                )
            )
        else:
            container.add_item(discord.ui.TextDisplay(f"## {title}"))

        description = _clean_description(embed.description)
        if description:
            container.add_item(discord.ui.TextDisplay(description[:1400]))

        body = _log_field_body(embed)
        if body:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(body[:3900]))

        footer = _plain(getattr(embed.footer, "text", None))
        if footer:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(f"-# {_safe_text(footer)[:500]}"))

        _append_buttons(container, legacy_view)
        self.add_item(container)


async def _send_log_v82(
    bot,
    guild: discord.Guild,
    log_type: str,
    embed: discord.Embed,
    file: discord.File | None = None,
    *,
    view: discord.ui.View | None = None,
    event_key: str | None = None,
) -> bool:
    if not log_service.is_primary_process():
        return False

    rendered = (
        embed
        if getattr(getattr(embed, "image", None), "url", None) == embeds.SENTRIX_BANNER_URL
        else embeds.normalize_log(embed)
    )
    semantic_key = log_service.semantic_event_key(guild.id, log_type, rendered)
    if log_service._is_duplicate(event_key) or log_service._is_duplicate(semantic_key):
        return False

    try:
        setting = await log_service.get_log_setting(bot, guild.id, log_type)
    except Exception:
        logger.exception("V82: impossible de lire le réglage de log %s sur %s", log_type, guild.id)
        return False
    if not setting["enabled"]:
        return False

    ok, reason = log_service.validate_channel(guild, setting["channel_id"], needs_file=file is not None)
    if not ok:
        logger.warning("V82: log %s non envoyé sur %s : %s", log_type, guild.id, reason)
        return False

    channel = guild.get_channel(setting["channel_id"])
    panel = PremiumLogViewV82(
        rendered,
        banner_url=embeds.SENTRIX_BANNER_URL,
        legacy_view=view,
    )
    kwargs: dict[str, Any] = {
        "view": panel,
        "allowed_mentions": log_service.LOG_ALLOWED_MENTIONS,
    }
    if file is not None:
        kwargs["file"] = file

    try:
        await channel.send(**kwargs)
        logger.info("Log V82 large envoyé guild=%s type=%s channel=%s", guild.id, log_type, channel.id)
        return True
    except (discord.Forbidden, discord.HTTPException):
        logger.exception("Échec d'envoi du log V82 %s dans %s", log_type, setting["channel_id"])
        return False


async def _send_test_log_v82(
    bot,
    guild: discord.Guild,
    log_type: str,
    author: discord.abc.User,
) -> tuple[bool, str]:
    setting = await log_service.get_log_setting(bot, guild.id, log_type)
    if not setting["enabled"]:
        return False, "Ce type de log est désactivé. Activez-le avant le test."
    ok, reason = log_service.validate_channel(guild, setting["channel_id"])
    if not ok:
        return False, f"Impossible d'envoyer un test : {reason}."

    test_embed = embeds.log_embed(
        "Test de log",
        fields=(
            ("Catégorie", log_service.LOG_TYPES.get(log_type, {}).get("label", log_type), False),
            ("Déclenché par", f"<@{author.id}>", True),
        ),
    )
    sent = await _send_log_v82(
        bot,
        guild,
        log_type,
        test_embed,
        event_key=log_service.make_event_key(guild.id, "test_log_v82", executor_id=author.id),
    )
    channel = guild.get_channel(setting["channel_id"])
    return (True, f"Test envoyé dans {channel.mention}.") if sent else (False, "Le test n'a pas pu être envoyé.")


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_premium_ui_v82", False):
        return

    # Les wrappers de V81 résolvent PremiumEmbedView au moment de l'appel : remplacer
    # la globale suffit donc pour +profile, /profile, +serverinfo et les ponts V81.
    v81.PremiumEmbedView = PremiumEmbedViewV82
    v81.PremiumLogView = PremiumLogViewV82

    _send_log_v82._sentrix_logs_v82 = True
    _send_test_log_v82._sentrix_logs_v82 = True
    log_service.send_log = _send_log_v82
    log_service.send_test_log = _send_test_log_v82

    bot._sentrix_premium_ui_v82 = True
    logger.info(
        "%s installé : profils aplatis et logs forcés en grand format avec bannière publique.",
        RUNTIME_MARKER,
    )


__all__ = ["install", "PremiumEmbedViewV82", "PremiumLogViewV82"]
