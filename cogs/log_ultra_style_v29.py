"""SentriX V29.5 — rendu premium propre et compact.

V27/V28 gardent la déduplication, les IDs, l'Audit Log et les mentions silencieuses.
V29.5 ne touche qu'au rendu : un seul vrai gros titre, le reste compact.
"""
from __future__ import annotations

import re

import discord
from discord.ext import commands

from . import premium_logs_v2
from . import log_premium_v28 as v28
from .log_rectangle_v25 import _event_timestamp, _field_value, _is_role_batch


SENTRIX_ICONS = {
    "brand": "🛡️",
    "audit": "🛰️",
    "secure": "🔐",
    "signal": "📡",
    "event": "💠",
    "watch": "🧿",
    "action": "⚡",
    "change": "🧬",
    "archive": "🗂️",
    "jump": "🔗",
}

EVENT_ICON = {
    "message_delete": "🗑️",
    "message_edit": SENTRIX_ICONS["change"],
    "member_ban": SENTRIX_ICONS["secure"],
    "member_unban": "🔓",
    "member_timeout": "⏱️",
    "member_role_update": SENTRIX_ICONS["action"],
    "channel_create": "➕",
    "channel_delete": "➖",
    "channel_update": SENTRIX_ICONS["audit"],
    "role_create": "➕",
    "role_delete": "➖",
    "role_update": SENTRIX_ICONS["action"],
    "guild_update": SENTRIX_ICONS["audit"],
}

EVENT_ACCENTS = {
    "message_delete": 0xED4245,
    "message_edit": 0x8B5CF6,
    "member_ban": 0xD83C3E,
    "member_unban": 0x57F287,
    "member_timeout": 0xEB459E,
    "member_role_update": 0x9B59B6,
    "channel_create": 0x57F287,
    "channel_delete": 0xED4245,
    "channel_update": 0x5865F2,
    "role_create": 0x57F287,
    "role_delete": 0xED4245,
    "role_update": 0x9B59B6,
    "guild_update": 0x5865F2,
}

EVENT_STATUS = {
    "message_delete": "Suppression",
    "message_edit": "Modification",
    "member_ban": "Bannissement",
    "member_unban": "Débannissement",
    "member_timeout": "Timeout",
    "member_role_update": "Rôles modifiés",
    "channel_create": "Salon créé",
    "channel_delete": "Salon supprimé",
    "channel_update": "Salon modifié",
    "role_create": "Rôle créé",
    "role_delete": "Rôle supprimé",
    "role_update": "Rôle modifié",
    "guild_update": "Serveur modifié",
}


def _plain_line(value: str | None, limit: int = 300) -> str:
    text = re.sub(r"\s*\n\s*", " · ", str(value or "").strip())
    text = re.sub(r"\s{2,}", " ", text)
    return (text or "Non disponible")[:limit]


def _event(log_type: str, embed: discord.Embed) -> str:
    return v28._event(log_type, embed)


def _accent(log_type: str, embed: discord.Embed) -> int:
    event = _event(log_type, embed)
    if event in EVENT_ACCENTS:
        return EVENT_ACCENTS[event]
    if embed.colour:
        return int(embed.colour.value)
    return {
        "moderation": 0xEB459E,
        "automod": 0xED4245,
        "security": 0xED4245,
        "voice": 0x3498DB,
        "tickets": 0x9B59B6,
        "economy": 0xF1C40F,
        "levels": 0x57F287,
        "ai": 0x5865F2,
        "games": 0x00A8FC,
    }.get(str(log_type), 0x7C5CFC)


def _mention(value: str | None) -> str:
    uid = v28._first_id(value)
    return f"<@{uid}>" if uid else _plain_line(value, 220)


def _event_title(log_type: str, embed: discord.Embed) -> str:
    raw = re.sub(r"\s+", " ", str(embed.title or "Journal SentriX")).strip()
    raw = re.sub(r"^[^\wÀ-ÿ]+\s*", "", raw).strip() or "Journal SentriX"
    return f"{EVENT_ICON.get(_event(log_type, embed), SENTRIX_ICONS['event'])} {raw}"


def _header(bot: commands.Bot, guild: discord.Guild, log_type: str, embed: discord.Embed) -> tuple[discord.ui.TextDisplay, str | None]:
    category, _ = v28._category(log_type)
    ts = _event_timestamp(embed)
    status = EVENT_STATUS.get(_event(log_type, embed), "Événement")
    text = (
        f"-# {SENTRIX_ICONS['brand']} SENTRIX • {category} • {guild.name}\n"
        f"# {_event_title(log_type, embed)}\n"
        f"-# {status} • <t:{ts}:R>"
    )[:3900]
    return discord.ui.TextDisplay(text), v28._avatar(bot, guild, embed)


def _meta_line(guild: discord.Guild, embed: discord.Embed) -> str:
    author = _field_value(embed, "auteur", "membre", "utilisateur", "cible")
    actor = _field_value(embed, "effectue par", "moderateur", "acteur", "executant")
    channel = v28._resolved_channel(guild, embed)
    channel_raw = _field_value(embed, "salon", "channel")
    ts = _event_timestamp(embed)

    author_text = _mention(author) if author else "Non disponible"
    salon_text = channel.mention if channel is not None else _plain_line(channel_raw, 180)
    line = f"**Auteur** {author_text}  •  **Salon** {salon_text}  •  <t:{ts}:t>"
    if actor:
        bot_tag = " `BOT`" if "bot" in v28._plain(actor) else ""
        line += f"\n-# Action par {_mention(actor)}{bot_tag}"
    return line[:3900]


def _edit_panel(embed: discord.Embed) -> str | None:
    before = _field_value(embed, "avant")
    after = _field_value(embed, "apres")
    if not before and not after:
        return None

    before = str(before or "Non disponible")[:1100].replace("\n", "\n> ")
    after = str(after or "Non disponible")[:1100].replace("\n", "\n> ")
    return (
        f"**Avant**\n> {before}\n\n"
        f"**Après**\n> {after}"
    )[:3900]


def _details_panel(embed: discord.Embed) -> str | None:
    if _is_role_batch(embed):
        text = (embed.description or "").strip()
        return text[:3000] if text else None

    content = _field_value(embed, "contenu")
    reason = _field_value(embed, "raison", "raison audit log")
    duration = _field_value(embed, "duree", "fin du timeout", "nouvel etat")
    attachments = _field_value(embed, "pieces jointes", "pièces jointes")

    rows: list[str] = []
    if content:
        quoted = str(content)[:1300].replace("\n", "\n> ")
        rows.append(f"**Contenu**\n> {quoted}")
    if reason:
        rows.append(f"**Raison** {_plain_line(reason, 500)}")
    if duration:
        rows.append(f"**Durée / état** {_plain_line(duration, 360)}")
    if attachments:
        rows.append(f"**Pièces jointes**\n{str(attachments)[:750]}")
    if not rows:
        description = (embed.description or "").strip()
        return description[:1200] if description else None
    return "\n\n".join(rows[:4])


def _message_jump_url(guild: discord.Guild, log_type: str, embed: discord.Embed) -> str | None:
    if _event(log_type, embed) != "message_edit":
        return None
    message_id = v28._message_id(log_type, embed)
    channel = v28._resolved_channel(guild, embed)
    if not message_id or channel is None:
        return None
    return f"https://discord.com/channels/{guild.id}/{channel.id}/{message_id}"


def _button_set(guild: discord.Guild, log_type: str, embed: discord.Embed, inherited: list[tuple[str, int]]) -> list[tuple[str, int]]:
    message_id = v28._message_id(log_type, embed)
    channel = v28._resolved_channel(guild, embed)
    author_id = v28._first_id(_field_value(embed, "auteur", "membre", "utilisateur", "cible"))

    result: list[tuple[str, int]] = []
    if message_id:
        result.append(("ID message", message_id))
    if channel is not None:
        result.append(("ID salon", channel.id))
    if author_id:
        result.append(("ID auteur", author_id))
    result.append(("ID serveur", guild.id))

    used = {value for _, value in result}
    for label, value in inherited:
        try:
            ivalue = int(value)
        except (TypeError, ValueError):
            continue
        if ivalue in used:
            continue
        result.append((str(label), ivalue))
        used.add(ivalue)
    return result[:4]


class UltraPremiumLogV29(discord.ui.LayoutView):
    _sentrix_log_layout = True
    _sentrix_rectangle_v25 = True
    _sentrix_reference_v26 = True
    _sentrix_unified_v27 = True
    _sentrix_premium_v28 = True
    _sentrix_ultra_v29 = True

    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        buttons: list[tuple[str, int]],
    ):
        super().__init__(timeout=6 * 60 * 60)
        clean = v28._silent_mention_embed(embed)
        v28.v27._restore_channel_mentions(guild, clean)
        clean = v28._ensure_message_id_field(log_type, clean)

        container = discord.ui.Container(accent_colour=_accent(log_type, clean))

        header, avatar = _header(bot, guild, log_type, clean)
        if avatar:
            try:
                container.add_item(
                    discord.ui.Section(
                        header,
                        accessory=discord.ui.Thumbnail(
                            avatar,
                            description="SentriX audit",
                        ),
                    )
                )
            except Exception:
                container.add_item(header)
        else:
            container.add_item(header)

        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(_meta_line(guild, clean)))

        event = _event(log_type, clean)
        body = _edit_panel(clean) if event == "message_edit" else _details_panel(clean)
        if body:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(body[:3900]))

        jump_url = _message_jump_url(guild, log_type, clean)
        final_buttons = _button_set(guild, log_type, clean, buttons)
        if jump_url or final_buttons:
            row = discord.ui.ActionRow()
            if jump_url:
                row.add_item(
                    discord.ui.Button(
                        label="Voir le message",
                        emoji=SENTRIX_ICONS["jump"],
                        style=discord.ButtonStyle.link,
                        url=jump_url,
                    )
                )
            for index, (label, value) in enumerate(final_buttons[:4]):
                row.add_item(premium_logs_v2.CopyIdButton(label, int(value), index))
            if row.children:
                container.add_item(row)

        container.add_item(discord.ui.TextDisplay("-# SentriX • Secure Audit"))

        self._sentrix_log_fingerprint = v28._fingerprint(guild, log_type, clean)
        self._sentrix_is_log_layout = True
        self.add_item(container)


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del bot, extension_name
    required = ("LayoutView", "Container", "Section", "TextDisplay", "Thumbnail", "Separator")
    if not all(hasattr(discord.ui, name) for name in required):
        return
    premium_logs_v2.PremiumLogLayout = UltraPremiumLogV29


__all__ = ["install", "UltraPremiumLogV29", "SENTRIX_ICONS"]
