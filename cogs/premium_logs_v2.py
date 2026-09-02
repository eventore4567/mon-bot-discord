"""Cartes premium Components V2 pour les logs SentriX.

Ce module s'installe APRES premium_logs.py et remplace visuellement les embeds standards
par une vraie carte Discord Components V2 : barre d'accent, section identité + thumbnail,
séparateurs, blocs de détails et boutons ID intégrés. Les logs avec fichier restent sur
l'embed premium classique pour ne jamais risquer de perdre une pièce jointe/transcript.

Discord Components V2 nécessite discord.py >= 2.6.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import discord
from discord.ext import commands

from utils import log_service
from .premium_logs import style_log, _button_items

logger = logging.getLogger("bot.premium-logs-v2")
_INSTALLED = False


FIELD_PRIORITY = {
    "membre": 0,
    "utilisateur": 0,
    "auteur": 1,
    "effectue par": 2,
    "moderateur": 2,
    "acteur": 2,
    "role attribue": 3,
    "role retire": 3,
    "role": 3,
    "duree": 4,
    "fin du timeout": 5,
    "fin": 5,
    "raison": 6,
    "raison audit log": 6,
    "salon": 7,
    "contenu": 8,
    "avant": 9,
    "apres": 10,
    "pieces jointes": 11,
    "acces": 12,
}


def _plain(value: str | None) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z0-9 ]+", " ", text).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _first_id(value: str | None) -> int | None:
    match = re.search(r"(?<!\d)(\d{15,22})(?!\d)", value or "")
    return int(match.group(1)) if match else None


def _field_value(embed: discord.Embed, *names: str) -> str:
    wanted = {_plain(name) for name in names}
    for field in embed.fields:
        current = _plain(str(field.name))
        if current in wanted or any(current.endswith(name) for name in wanted):
            return str(field.value)
    return ""


def _timeout_end_timestamp(embed: discord.Embed) -> int | None:
    for field in embed.fields:
        if "timeout" not in _plain(str(field.name)) and "nouvel etat" not in _plain(str(field.name)):
            continue
        match = re.search(r"<t:(\d+)(?::[A-Za-z])?>", str(field.value))
        if match:
            return int(match.group(1))
    return None


def _nice_duration(seconds: float) -> str:
    """Durée lisible, arrondie aux unités naturelles des sanctions."""
    seconds = max(0, int(round(seconds)))
    # Une interaction/audit peut ajouter 1-2 s de délai. Pour les durées courantes,
    # on arrondit à la minute la plus proche afin qu'un timeout de 10 min affiche 10 min.
    if seconds >= 60:
        seconds = int(round(seconds / 60)) * 60

    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} jour{'s' if days > 1 else ''}")
    if hours:
        parts.append(f"{hours} h")
    if minutes:
        parts.append(f"{minutes} min")
    if seconds and not parts:
        parts.append(f"{seconds} s")
    return " ".join(parts[:3]) or "moins d’une seconde"


def _source_timestamp(source: discord.Embed) -> float:
    stamp = source.timestamp
    if stamp is None:
        return datetime.now(timezone.utc).timestamp()
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()


def _fix_timeout_duration(styled: discord.Embed, source: discord.Embed) -> None:
    end_ts = _timeout_end_timestamp(source)
    if end_ts is None:
        return
    duration = _nice_duration(end_ts - _source_timestamp(source))
    for index, field in enumerate(list(styled.fields)):
        if "duree" in _plain(str(field.name)):
            styled.set_field_at(index, name="⏱️ Durée", value=f"**{duration}**", inline=field.inline)
            return
    styled.add_field(name="⏱️ Durée", value=f"**{duration}**", inline=True)


def _thumbnail_url(embed: discord.Embed, bot: commands.Bot, guild: discord.Guild) -> str | None:
    thumb = getattr(embed.thumbnail, "url", None)
    if thumb:
        return str(thumb)
    if guild.icon:
        return str(guild.icon.url)
    if bot.user:
        return str(bot.user.display_avatar.url)
    return None


def _compact_header(embed: discord.Embed, guild: discord.Guild, log_type: str) -> str:
    title = str(embed.title or "📋 Log")
    description = (embed.description or "").strip()
    category = {
        "messages": "MESSAGES",
        "members": "MEMBRES",
        "roles": "RÔLES",
        "server": "SERVEUR",
        "voice": "VOCAL",
        "moderation": "MODÉRATION",
        "automod": "SÉCURITÉ",
        "tickets": "TICKETS",
        "economy": "ÉCONOMIE",
        "levels": "NIVEAUX",
        "ai": "IA",
        "games": "JEUX",
        "system": "SYSTÈME",
    }.get(log_type, log_type.upper())

    lines = [
        f"-# 🛡️ SENTRIX  •  {category}  •  {guild.name}",
        f"## {title}",
    ]
    if description:
        lines.append(description)
    return "\n".join(lines)[:4000]


def _field_paragraph(field: discord.EmbedProxy) -> str:
    name = str(field.name).strip()
    value = str(field.value).strip() or "*Aucune information*"
    return f"**{name}**\n{value}"


def _ordered_fields(embed: discord.Embed) -> list[discord.EmbedProxy]:
    indexed = list(enumerate(embed.fields))

    def key(pair):
        index, field = pair
        name = _plain(str(field.name))
        priority = 50
        for label, score in FIELD_PRIORITY.items():
            if label in name:
                priority = min(priority, score)
        return priority, index

    return [field for _, field in sorted(indexed, key=key)]


def _split_blocks(paragraphs: list[str], limit: int = 3800) -> list[str]:
    blocks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        paragraph = paragraph[:3500]
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            blocks.append(current)
        current = paragraph
    if current:
        blocks.append(current)
    return blocks[:8]


def _button_label(old_label: str) -> tuple[str, str | None]:
    text = _plain(old_label)
    if "moderateur" in text:
        return "ID modérateur", "🛡️"
    if "membre" in text:
        return "ID membre", "👤"
    if "auteur" in text:
        return "ID auteur", "👤"
    if "message" in text:
        return "ID message", "💬"
    if "role" in text:
        return "ID rôle", "🏷️"
    if "salon" in text:
        return "ID salon", "#️⃣"
    if "serveur" in text:
        return "ID serveur", "🖥️"
    return old_label.replace("Copier ", "")[:80], "📋"


class CopyIdButton(discord.ui.Button):
    def __init__(self, label: str, value: int, index: int):
        short_label, emoji = _button_label(label)
        super().__init__(
            label=short_label,
            emoji=emoji,
            style=discord.ButtonStyle.secondary,
            custom_id=f"sentrix_log_v2_copy:{index}:{int(value)}",
        )
        self.value = int(value)
        self.kind = short_label

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"📋 **{self.kind}**\n```{self.value}```",
            ephemeral=True,
        )


class PremiumLogLayout(discord.ui.LayoutView):
    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        buttons: list[tuple[str, int]],
    ):
        super().__init__(timeout=6 * 60 * 60)
        accent = int(embed.colour.value) if embed.colour else 0x7C5CFC
        container = discord.ui.Container(accent_colour=accent)

        header = discord.ui.TextDisplay(_compact_header(embed, guild, log_type))
        thumbnail = _thumbnail_url(embed, bot, guild)
        if thumbnail:
            container.add_item(
                discord.ui.Section(
                    header,
                    accessory=discord.ui.Thumbnail(thumbnail),
                )
            )
        else:
            container.add_item(header)

        container.add_item(discord.ui.Separator())

        paragraphs = [_field_paragraph(field) for field in _ordered_fields(embed)]
        if paragraphs:
            for block in _split_blocks(paragraphs):
                container.add_item(discord.ui.TextDisplay(block))
        elif not embed.description:
            container.add_item(discord.ui.TextDisplay("*Aucun détail supplémentaire.*"))

        image_url = getattr(embed.image, "url", None)
        if image_url:
            gallery = discord.ui.MediaGallery()
            gallery.add_item(media=str(image_url))
            container.add_item(discord.ui.Separator())
            container.add_item(gallery)

        container.add_item(discord.ui.Separator())
        now_ts = int(datetime.now(timezone.utc).timestamp())
        target_id = _first_id(getattr(embed.footer, "text", None))
        footer = f"-# SentriX • Journal sécurisé • <t:{now_ts}:R>"
        if target_id:
            footer += f" • ID `{target_id}`"
        container.add_item(discord.ui.TextDisplay(footer))

        if buttons:
            row = discord.ui.ActionRow()
            seen: set[tuple[str, int]] = set()
            for index, (label, value) in enumerate(buttons[:5]):
                key = (label, int(value))
                if key in seen:
                    continue
                seen.add(key)
                row.add_item(CopyIdButton(label, int(value), index))
            if row.children:
                container.add_item(row)

        self.add_item(container)


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # Components V2 sont disponibles à partir de discord.py 2.6. Si jamais Railway
    # démarre avec une version plus ancienne, on garde automatiquement premium_logs.py.
    if not all(hasattr(discord.ui, name) for name in ("LayoutView", "Container", "Section", "TextDisplay")):
        logger.warning("Components V2 indisponibles : conservation du style premium embed classique.")
        return

    original_send = log_service.send_log
    if getattr(original_send, "_sentrix_premium_logs_v2", False):
        _INSTALLED = True
        return

    async def send_premium_v2(
        inner_bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        file: discord.File | None = None,
    
        **identity,
    ) -> bool:
        # Les fichiers/transcripts restent sur l'embed premium précédent. Components V2
        # peut gérer des fichiers, mais garder ce chemin évite toute régression d'attachment.
        if file is not None:
            return await original_send(inner_bot, guild, log_type, embed, file=file, **identity)

        try:
            styled = style_log(inner_bot, guild, log_type, embed, **identity)
            _fix_timeout_duration(styled, embed)
            buttons = _button_items(styled, str(styled.title or ""))

            setting = await log_service.get_log_setting(inner_bot, guild.id, log_type)
            if not setting["enabled"]:
                return False

            ok, _reason = log_service.validate_channel(guild, setting["channel_id"])
            if not ok:
                try:
                    from .moderation_logs_fix import _repair_log_target
                    repaired = await _repair_log_target(inner_bot, guild, log_type)
                except Exception:
                    repaired = None
                if not repaired:
                    return False
                setting = await log_service.get_log_setting(inner_bot, guild.id, log_type)
                ok, _reason = log_service.validate_channel(guild, setting["channel_id"])
                if not ok:
                    return False

            channel = guild.get_channel(setting["channel_id"])
            if not isinstance(channel, discord.TextChannel):
                return False

            layout = PremiumLogLayout(inner_bot, guild, log_type, styled, buttons)
            await channel.send(view=layout)
            return True
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Carte Components V2 refusée (%s, guild=%s), fallback embed premium.",
                log_type,
                guild.id,
                exc_info=True,
            )
        except Exception:
            logger.exception(
                "Erreur de rendu Components V2 (%s, guild=%s), fallback embed premium.",
                log_type,
                guild.id,
            )

        # Aucun log perdu si Discord/API/UI change : le sender premium v1 reste le secours.
        try:
            return await original_send(inner_bot, guild, log_type, embed, file=file, **identity)
        except Exception:
            return False

    send_premium_v2._sentrix_premium_logs_v2 = True
    log_service.send_log = send_premium_v2
    _INSTALLED = True
    logger.info("Cartes premium Components V2 des logs activées.")
