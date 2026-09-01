"""SentriX V81 — interface premium pour logs, profil et commandes d'information.

Objectifs :
- logs larges en Components V2 avec une vraie bande horizontale en haut ;
- profil compact au lieu d'un embed vertical interminable ;
- commandes racines +serverinfo et +leaderboard réellement disponibles ;
- conservation des boutons existants des logs (copie d'ID, etc.) et des fichiers joints.

Cette couche est volontairement installée au runtime au-dessus des cogs existants : la logique
métier et les données restent celles des commandes officielles déjà testées.
"""
from __future__ import annotations

import binascii
import io
import logging
import re
import struct
import zlib
from typing import Any

import discord
from discord.ext import commands

from utils import log_service

logger = logging.getLogger("bot.premium-ui-v81")
RUNTIME_MARKER = "Premium UI V81"
ACCENT = discord.Colour(0x6D5DFB)

_BANNER_RGB = {
    "error": ((255, 56, 83), (125, 20, 48)),
    "success": ((47, 211, 105), (16, 112, 65)),
    "warning": ((255, 174, 51), (174, 77, 20)),
    "info": ((54, 143, 255), (43, 72, 194)),
    "special": ((156, 89, 255), (73, 41, 180)),
}


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)


def _banner_png(kind: str, width: int = 1024, height: int = 28) -> bytes:
    """Génère une bande PNG 1024px avec dégradé et ouverture transparente centrale."""
    left, right = _BANNER_RGB.get(kind, _BANNER_RGB["info"])
    rows = bytearray()
    center = width / 2
    hole_half = 62
    fade = 28

    for y in range(height):
        rows.append(0)  # filtre PNG None
        for x in range(width):
            t = x / max(1, width - 1)
            r = round(left[0] + (right[0] - left[0]) * t)
            g = round(left[1] + (right[1] - left[1]) * t)
            b = round(left[2] + (right[2] - left[2]) * t)

            distance = abs(x - center)
            if distance <= hole_half:
                alpha = 0
            elif distance < hole_half + fade:
                alpha = round(255 * ((distance - hole_half) / fade))
            else:
                alpha = 255

            # Une légère luminosité au centre vertical évite une bande plate.
            vertical = 0.88 + 0.12 * (1 - abs((y / max(1, height - 1)) * 2 - 1))
            rows.extend((round(r * vertical), round(g * vertical), round(b * vertical), alpha))

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return signature + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + _png_chunk(b"IEND", b"")


def _plain(value: object) -> str:
    return str(value or "").strip()


def _safe_text(value: object) -> str:
    text = _plain(value)
    text = re.sub(r"@(everyone|here)\b", lambda m: "@\u200b" + m.group(1), text, flags=re.IGNORECASE)
    return text


def _banner_kind(log_type: str, embed: discord.Embed) -> str:
    title = _plain(embed.title).casefold()
    description = _plain(embed.description).casefold()
    haystack = f"{log_type} {title} {description}"

    if any(word in haystack for word in ("unban", "unmute", "restaur", "réussi", "reussi", "succès", "succes")):
        return "success"
    if any(word in haystack for word in ("warn", "avert", "mute", "timeout", "automod", "permission", "anti-spam", "antispam")):
        return "warning"
    if any(word in haystack for word in ("arriv", "rejoint", "bienvenue", "special", "spécial")):
        return "special"
    if any(word in haystack for word in ("supprim", "delete", "ban", "kick", "expuls", "sanction", "erreur", "error", "départ", "depart")):
        return "error"
    return "info"


def _footer_text(embed: discord.Embed) -> str:
    footer = _plain(getattr(embed.footer, "text", None))
    if footer:
        return footer
    if embed.timestamp is not None:
        return discord.utils.format_dt(embed.timestamp, style="f")
    return "SentriX"


def _compact_pairs(value: str) -> str:
    lines = [_safe_text(line).strip() for line in str(value or "").splitlines() if _safe_text(line).strip()]
    if not lines:
        return "—"

    if all(line.startswith(("•", "-")) for line in lines):
        return " • ".join(line.lstrip("•- ") for line in lines)

    # Les anciens profils utilisent souvent : libellé, valeur, libellé, valeur.
    if len(lines) >= 4 and len(lines) % 2 == 0:
        pairs: list[str] = []
        usable = True
        for index in range(0, len(lines), 2):
            label = lines[index].strip("* _:`")
            value_line = lines[index + 1]
            if len(label) > 45 or len(value_line) > 80:
                usable = False
                break
            if not value_line.startswith("**"):
                value_line = f"**{value_line.strip('*')}**"
            pairs.append(f"{label} {value_line}")
        if usable:
            return " • ".join(pairs)

    if len(lines) <= 4 and all(len(line) < 90 for line in lines):
        return " • ".join(lines)
    return "\n".join(lines)


def _embed_body(embed: discord.Embed, *, compact: bool = False) -> list[str]:
    blocks: list[str] = []
    description = _safe_text(embed.description)
    if description:
        blocks.append(description[:1400])

    for field in embed.fields:
        name = _safe_text(field.name)
        value = _safe_text(field.value)
        if not name or not value:
            continue
        rendered = _compact_pairs(value) if compact else value
        blocks.append(f"### {name}\n{rendered}")
        if len("\n\n".join(blocks)) > 3300:
            break
    return blocks


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
        logger.debug("Bouton legacy impossible à recopier dans V81", exc_info=True)
        return None


def _append_legacy_buttons(container: discord.ui.Container, legacy_view: discord.ui.View | None) -> None:
    if legacy_view is None:
        return
    buttons: list[discord.ui.Button] = []
    for item in getattr(legacy_view, "children", ()):  # copie ID auteur/message incluse
        if isinstance(item, discord.ui.Button):
            clone = _clone_button(item)
            if clone is not None:
                buttons.append(clone)
    if not buttons:
        return
    container.add_item(discord.ui.Separator())
    for index in range(0, len(buttons), 5):
        container.add_item(discord.ui.ActionRow(*buttons[index:index + 5]))


class PremiumEmbedView(discord.ui.LayoutView):
    """Convertit un ancien embed en panneau Components V2 compact."""

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
        description = _safe_text(embed.description)
        thumbnail = _plain(getattr(embed.thumbnail, "url", None))

        header = f"# {title}"
        if description:
            header += f"\n{description[:900]}"

        if thumbnail:
            container.add_item(
                discord.ui.Section(
                    discord.ui.TextDisplay(header),
                    accessory=discord.ui.Thumbnail(thumbnail, description="SentriX"),
                )
            )
        else:
            container.add_item(discord.ui.TextDisplay(header))

        fields_only = discord.Embed()
        for field in embed.fields:
            fields_only.add_field(name=field.name, value=field.value, inline=field.inline)
        blocks = _embed_body(fields_only, compact=compact)
        if blocks:
            container.add_item(discord.ui.Separator())
            for block in blocks:
                container.add_item(discord.ui.TextDisplay(block[:3900]))

        footer = _footer_text(embed)
        if footer:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(f"-# {_safe_text(footer)[:500]}"))

        _append_legacy_buttons(container, legacy_view)
        self.add_item(container)


class PremiumLogView(discord.ui.LayoutView):
    def __init__(
        self,
        embed: discord.Embed,
        *,
        banner_filename: str | None,
        legacy_view: discord.ui.View | None,
    ):
        super().__init__(timeout=getattr(legacy_view, "timeout", 300) if legacy_view is not None else 300)
        container = discord.ui.Container()  # pas de barre latérale : la couleur est dans la bande du haut

        if banner_filename:
            gallery = discord.ui.MediaGallery()
            gallery.add_item(media=f"attachment://{banner_filename}", description="Bannière SentriX")
            container.add_item(gallery)

        title = _safe_text(embed.title or "Journal SentriX")
        thumbnail = _plain(getattr(embed.thumbnail, "url", None))
        if thumbnail:
            container.add_item(
                discord.ui.Section(
                    discord.ui.TextDisplay(f"# {title}"),
                    accessory=discord.ui.Thumbnail(thumbnail, description="SentriX"),
                )
            )
        else:
            container.add_item(discord.ui.TextDisplay(f"# {title}"))

        description = _safe_text(embed.description)
        if description:
            container.add_item(discord.ui.TextDisplay(description[:1800]))

        if embed.fields:
            container.add_item(discord.ui.Separator())
            for field in embed.fields:
                name = _safe_text(field.name)
                value = _safe_text(field.value)
                if name and value:
                    container.add_item(discord.ui.TextDisplay(f"**{name}**\n{value}"[:3900]))

        footer = _footer_text(embed)
        if footer:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(f"-# {_safe_text(footer)[:500]}"))

        _append_legacy_buttons(container, legacy_view)
        self.add_item(container)


async def _send_log_v81(
    bot,
    guild: discord.Guild,
    log_type: str,
    embed: discord.Embed,
    file: discord.File | None = None,
    *,
    view: discord.ui.View | None = None,
    event_key: str | None = None,

    **identity,
) -> bool:
    """Remplacement du transport central : mêmes réglages/déduplication, nouveau rendu V2."""
    if not log_service.is_primary_process():
        return False

    from utils import embeds as embeds_mod

    rendered = (
        embed
        if getattr(getattr(embed, "image", None), "url", None) == embeds_mod.SENTRIX_BANNER_URL
        else embeds_mod.normalize_log(embed)
    )
    semantic_key = log_service.semantic_event_key(guild.id, log_type, rendered)
    if log_service._is_duplicate(event_key) or log_service._is_duplicate(semantic_key):
        return False

    try:
        setting = await log_service.get_log_setting(bot, guild.id, log_type)
    except Exception:
        logger.exception("V81: impossible de lire le réglage de log %s sur %s", log_type, guild.id)
        return False
    if not setting["enabled"]:
        return False

    # Le transcript éventuel est prioritaire : s'il existe, Attach Files est obligatoire.
    ok, reason = log_service.validate_channel(guild, setting["channel_id"], needs_file=file is not None)
    if not ok:
        logger.warning("V81: log %s non envoyé sur %s : %s", log_type, guild.id, reason)
        return False

    channel = guild.get_channel(setting["channel_id"])
    me = guild.me
    can_attach = bool(me and channel.permissions_for(me).attach_files)
    kind = _banner_kind(log_type, rendered)
    banner_filename: str | None = None
    files: list[discord.File] = []

    if can_attach:
        banner_filename = f"sentrix_banner_{kind}.png"
        files.append(discord.File(io.BytesIO(_banner_png(kind)), filename=banner_filename))
    if file is not None:
        files.append(file)

    panel = PremiumLogView(rendered, banner_filename=banner_filename, legacy_view=view)
    kwargs: dict[str, Any] = {
        "view": panel,
        "allowed_mentions": log_service.LOG_ALLOWED_MENTIONS,
    }
    if files:
        kwargs["files"] = files

    try:
        await channel.send(**kwargs)
        logger.info("Log V81 envoyé guild=%s type=%s channel=%s bande=%s", guild.id, log_type, channel.id, kind)
        return True
    except (discord.Forbidden, discord.HTTPException):
        logger.exception("Échec d'envoi du log V81 %s dans %s", log_type, setting["channel_id"])
        return False


async def _send_test_log_v81(bot, guild: discord.Guild, log_type: str, author: discord.abc.User) -> tuple[bool, str]:
    setting = await log_service.get_log_setting(bot, guild.id, log_type)
    if not setting["enabled"]:
        return False, "Ce type de log est désactivé. Activez-le avant le test."
    ok, reason = log_service.validate_channel(guild, setting["channel_id"])
    if not ok:
        return False, f"Impossible d'envoyer un test : {reason}."

    from utils import embeds as embeds_mod

    test_embed = embeds_mod.log_embed(
        "Test de log",
        fields=(("Catégorie", log_service.LOG_TYPES.get(log_type, {}).get("label", log_type), False), ("Déclenché par", f"<@{author.id}>", True)),
    )
    sent = await _send_log_v81(
        bot,
        guild,
        log_type,
        test_embed,
        event_key=log_service.make_event_key(guild.id, "test_log_v81", executor_id=author.id),
    )
    channel = guild.get_channel(setting["channel_id"])
    return (True, f"Test envoyé dans {channel.mention}.") if sent else (False, "Le test n'a pas pu être envoyé.")


async def _capture_embed(ctx: commands.Context, callback) -> tuple[discord.Embed | None, discord.ui.View | None]:
    original_send = ctx.send
    captured_embed: discord.Embed | None = None
    captured_view: discord.ui.View | None = None

    async def capture_send(content=None, **kwargs):
        nonlocal captured_embed, captured_view
        candidate = kwargs.get("embed")
        if candidate is None:
            embeds_list = kwargs.get("embeds") or []
            candidate = embeds_list[0] if embeds_list else None
        if isinstance(candidate, discord.Embed):
            captured_embed = candidate
            candidate_view = kwargs.get("view")
            captured_view = candidate_view if isinstance(candidate_view, discord.ui.View) else None
            return None
        return await original_send(content, **kwargs)

    ctx.send = capture_send
    try:
        await callback()
    finally:
        ctx.send = original_send
    return captured_embed, captured_view


async def _send_premium_from_target(ctx: commands.Context, target: commands.Command, *, title: str | None = None, compact: bool = False) -> None:
    original_send = ctx.send

    async def invoke_target():
        await ctx.invoke(target)

    embed, legacy_view = await _capture_embed(ctx, invoke_target)
    if embed is None:
        return
    panel = PremiumEmbedView(embed, compact=compact, legacy_view=legacy_view, title_override=title)
    await original_send(view=panel, allowed_mentions=discord.AllowedMentions.none())


def _install_bridge(bot: commands.Bot, name: str, target_name: str, description: str, *, compact: bool = False) -> None:
    if bot.get_command(name) is not None:
        return
    target = bot.get_command(target_name)
    if target is None:
        logger.warning("V81: cible +%s introuvable pour +%s", target_name, name)
        return

    async def bridge(ctx: commands.Context):
        await _send_premium_from_target(ctx, target, title=None, compact=compact)

    bridge.__name__ = f"sentrix_{name.replace('-', '_')}_v81"
    bridge.__doc__ = description

    # HybridCommand donne à la fois +nom et /nom. Si un slash homonyme existe déjà,
    # on garde seulement le pont préfixé pour éviter un conflit dans CommandTree.
    slash_exists = bot.tree.get_command(name, type=discord.AppCommandType.chat_input) is not None
    if slash_exists:
        command: commands.Command = commands.Command(bridge, name=name, description=description)
    else:
        command = commands.HybridCommand(bridge, name=name, description=description)
    bot.add_command(command)
    logger.info("V81: +%s ajouté -> +%s", name, target_name)


def _install_profile(bot: commands.Bot) -> None:
    command = bot.get_command("profile")
    if command is None:
        logger.warning("V81: commande profile introuvable")
        return
    current = command.callback
    if getattr(current, "_sentrix_profile_v81", False):
        return

    async def profile_v81(self, ctx: commands.Context, membre: discord.Member = None):
        original_send = ctx.send

        async def invoke_original():
            await current(self, ctx, membre)

        embed, legacy_view = await _capture_embed(ctx, invoke_original)
        if embed is None:
            return
        panel = PremiumEmbedView(embed, compact=True, legacy_view=legacy_view)
        await original_send(view=panel, allowed_mentions=discord.AllowedMentions.none())

    profile_v81._sentrix_profile_v81 = True
    profile_v81._sentrix_previous = current
    command.callback = profile_v81
    logger.info("V81: +profile / /profile passent par le panneau compact Components V2")


def _install_log_renderer() -> None:
    """Ne remplace plus le transport des logs.

    _send_log_v81 etait un pipeline complet parallele (route, dedup, rendu, envoi) qui
    n'appelait jamais utils.wide_logs.send_wide_log. Les couches de rendu premium
    restent utilisees pour les profils et les embeds de commandes ; les journaux passent
    exclusivement par utils.log_service.
    """
    return None


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_premium_ui_v81", False):
        return
    _install_log_renderer()
    _install_profile(bot)
    _install_bridge(bot, "serverinfo", "info serveur", "Afficher les informations détaillées du serveur.", compact=True)
    _install_bridge(bot, "leaderboard", "leaderboard-levels", "Afficher le classement des niveaux.", compact=False)
    bot._sentrix_premium_ui_v81 = True
    logger.info("%s installé", RUNTIME_MARKER)


__all__ = ["install", "PremiumEmbedView", "PremiumLogView", "_banner_png", "_banner_kind"]
