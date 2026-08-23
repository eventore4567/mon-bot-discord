"""SentriX V30 — style préféré : large, lisible et équilibré.

Cette couche ne change pas la logique des logs. V27/V28 gardent :
- anti-doublon ;
- Audit Log et actions des autres bots ;
- IDs ;
- vraies mentions cliquables avec AllowedMentions.none().

V30 remet uniquement le rendu visuel préféré : gros titre, CONTEXTE, DÉTAILS,
avatar à droite et rangée de boutons en bas. Les messages modifiés gardent le bouton
Voir le message et un bloc Avant / Après.
"""
from __future__ import annotations

import re

import discord
from discord.ext import commands

from . import premium_logs_v2
from . import log_premium_v28 as v28
from .log_rectangle_v25 import _event_timestamp, _field_value, _is_role_batch


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

EVENT_ICON = {
    "message_delete": "🗑️",
    "message_edit": "✏️",
    "member_ban": "🔨",
    "member_unban": "🔓",
    "member_timeout": "⏱️",
    "member_role_update": "🏷️",
    "channel_create": "➕",
    "channel_delete": "➖",
    "channel_update": "⚙️",
    "role_create": "➕",
    "role_delete": "➖",
    "role_update": "⚙️",
    "guild_update": "⚙️",
}

EVENT_STATUS = {
    "message_delete": "SUPPRESSION",
    "message_edit": "MODIFICATION",
    "member_ban": "SANCTION",
    "member_unban": "RÉTABLISSEMENT",
    "member_timeout": "RESTRICTION",
    "member_role_update": "PERMISSIONS",
    "channel_create": "CRÉATION",
    "channel_delete": "SUPPRESSION",
    "channel_update": "CONFIGURATION",
    "role_create": "CRÉATION",
    "role_delete": "SUPPRESSION",
    "role_update": "CONFIGURATION",
    "guild_update": "CONFIGURATION",
}

STATUS_DOT = {
    "message_delete": "🔴",
    "message_edit": "🟣",
    "member_ban": "🔴",
    "member_unban": "🟢",
    "member_timeout": "🟣",
    "member_role_update": "🟣",
    "channel_create": "🟢",
    "channel_delete": "🔴",
    "channel_update": "🔵",
    "role_create": "🟢",
    "role_delete": "🔴",
    "role_update": "🟣",
    "guild_update": "🔵",
}


def _event(log_type: str, embed: discord.Embed) -> str:
    return v28._event(log_type, embed)


def _plain(value: str | None, limit: int = 320) -> str:
    text = re.sub(r"\s*\n\s*", " · ", str(value or "").strip())
    text = re.sub(r"\s{2,}", " ", text)
    text = text or "Non disponible"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _mention(value: str | None) -> str:
    uid = v28._first_id(value)
    return f"<@{uid}>" if uid else _plain(value, 220)


def _accent(log_type: str, embed: discord.Embed) -> int:
    event = _event(log_type, embed)
    if event in EVENT_ACCENTS:
        return EVENT_ACCENTS[event]
    if embed.colour:
        return int(embed.colour.value)
    return 0x7C5CFC


def _title(log_type: str, embed: discord.Embed) -> str:
    raw = re.sub(r"\s+", " ", str(embed.title or "Journal SentriX")).strip()
    raw = re.sub(r"^[^\wÀ-ÿ]+\s*", "", raw).strip() or "Journal SentriX"
    return f"{EVENT_ICON.get(_event(log_type, embed), '📋')} {raw}"


def _header(bot: commands.Bot, guild: discord.Guild, log_type: str, embed: discord.Embed):
    category, _ = v28._category(log_type)
    event = _event(log_type, embed)
    status = EVENT_STATUS.get(event, "ÉVÉNEMENT")
    dot = STATUS_DOT.get(event, "⚪")
    ts = _event_timestamp(embed)
    summary = v28._summary(log_type, embed)
    text = (
        f"-# ✦ SENTRIX  /  💬 {category}  /  SECURE AUDIT\n\n"
        f"# {_title(log_type, embed)}\n"
        f"{dot} **{status}**  ·  <t:{ts}:R>  ·  `LIVE LOG`\n"
        f"{summary}"
    )[:3900]
    return discord.ui.TextDisplay(text), v28._avatar(bot, guild, embed)


def _context(guild: discord.Guild, embed: discord.Embed) -> str:
    channel = v28._resolved_channel(guild, embed)
    channel_raw = _field_value(embed, "salon", "channel")
    target = _field_value(embed, "auteur", "membre", "utilisateur", "cible")
    actor = _field_value(embed, "effectue par", "moderateur", "acteur", "executant")

    rows: list[str] = []
    if channel is not None:
        rows.append(f"💬 **Salon**  {channel.mention}")
    elif channel_raw:
        rows.append(f"💬 **Salon**  {_plain(channel_raw, 240)}")
    if target:
        rows.append(f"👤 **Cible**  {_mention(target)}")
    if actor:
        bot_tag = "  `BOT`" if "bot" in v28._plain(actor) else ""
        rows.append(f"🛡️ **Action par**  {_mention(actor)}{bot_tag}")
    if not rows:
        rows.append(f"🖥️ **Serveur**  **{discord.utils.escape_markdown(guild.name)}**")
    return "### CONTEXTE\n" + "\n".join(f"> {row}" for row in rows[:3])


def _details(embed: discord.Embed) -> str | None:
    if _is_role_batch(embed):
        text = (embed.description or "").strip()
        return f"### DÉTAILS\n{text[:3000]}" if text else None

    content = _field_value(embed, "contenu")
    reason = _field_value(embed, "raison", "raison audit log")
    duration = _field_value(embed, "duree", "fin du timeout", "nouvel etat")
    attachments = _field_value(embed, "pieces jointes", "pièces jointes")

    rows: list[str] = []
    if content:
        quoted = str(content)[:1300].replace("\n", "\n> ")
        rows.append(f"**📝 Contenu**\n> {quoted}")
    if reason:
        rows.append(f"**📌 Raison**  {_plain(reason, 500)}")
    if duration:
        rows.append(f"**⏱️ Durée / état**  {_plain(duration, 360)}")
    if attachments:
        rows.append(f"**📎 Pièces jointes**\n{str(attachments)[:750]}")
    if not rows:
        return None
    return "### DÉTAILS\n" + "\n\n".join(rows[:4])


def _edit_details(embed: discord.Embed) -> str | None:
    before = _field_value(embed, "avant")
    after = _field_value(embed, "apres")
    if not before and not after:
        return _details(embed)
    before_text = str(before or "Non disponible")[:1100].replace("\n", "\n> ")
    after_text = str(after or "Non disponible")[:1100].replace("\n", "\n> ")
    return (
        "### DÉTAILS\n"
        f"**◀ Avant**\n> {before_text}\n\n"
        f"**▶ Après**\n> {after_text}"
    )[:3900]


def _message_jump_url(guild: discord.Guild, log_type: str, embed: discord.Embed) -> str | None:
    if _event(log_type, embed) != "message_edit":
        return None
    message_id = v28._message_id(log_type, embed)
    channel = v28._resolved_channel(guild, embed)
    if not message_id or channel is None:
        return None
    return f"https://discord.com/channels/{guild.id}/{channel.id}/{message_id}"


def _id_buttons(guild: discord.Guild, log_type: str, embed: discord.Embed) -> list[tuple[str, int]]:
    message_id = v28._message_id(log_type, embed)
    channel = v28._resolved_channel(guild, embed)
    author_id = v28._first_id(_field_value(embed, "auteur", "membre", "utilisateur", "cible"))

    result: list[tuple[str, int]] = []
    if message_id:
        result.append(("💬 ID message", message_id))
    if channel is not None:
        result.append(("#️⃣ ID salon", channel.id))
    if author_id:
        result.append(("👤 ID auteur", author_id))
    result.append(("🖥️ ID serveur", guild.id))
    return result[:4]


class PreferredLogV30(discord.ui.LayoutView):
    _sentrix_log_layout = True
    _sentrix_rectangle_v25 = True
    _sentrix_reference_v26 = True
    _sentrix_unified_v27 = True
    _sentrix_premium_v28 = True
    _sentrix_ultra_v29 = True
    _sentrix_preferred_v30 = True

    def __init__(self, bot: commands.Bot, guild: discord.Guild, log_type: str, embed: discord.Embed, buttons: list[tuple[str, int]]):
        super().__init__(timeout=6 * 60 * 60)
        clean = v28._silent_mention_embed(embed)
        v28.v27._restore_channel_mentions(guild, clean)
        clean = v28._ensure_message_id_field(log_type, clean)

        container = discord.ui.Container(accent_colour=_accent(log_type, clean))
        header, avatar = _header(bot, guild, log_type, clean)
        if avatar:
            try:
                container.add_item(discord.ui.Section(
                    header,
                    accessory=discord.ui.Thumbnail(avatar, description="SentriX audit"),
                ))
            except Exception:
                container.add_item(header)
        else:
            container.add_item(header)

        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(_context(guild, clean)[:3900]))

        event = _event(log_type, clean)
        body = _edit_details(clean) if event == "message_edit" else _details(clean)
        if body:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(body[:3900]))

        jump_url = _message_jump_url(guild, log_type, clean)
        ids = _id_buttons(guild, log_type, clean)
        if jump_url or ids:
            row = discord.ui.ActionRow()
            if jump_url:
                row.add_item(discord.ui.Button(
                    label="Voir le message",
                    emoji="🔗",
                    style=discord.ButtonStyle.link,
                    url=jump_url,
                ))
            for index, (label, value) in enumerate(ids):
                row.add_item(premium_logs_v2.CopyIdButton(label, int(value), index))
            if row.children:
                container.add_item(row)

        self._sentrix_log_fingerprint = v28._fingerprint(guild, log_type, clean)
        self._sentrix_is_log_layout = True
        self.add_item(container)


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del bot, extension_name
    required = ("LayoutView", "Container", "Section", "TextDisplay", "Thumbnail", "Separator")
    if not all(hasattr(discord.ui, name) for name in required):
        return
    premium_logs_v2.PremiumLogLayout = PreferredLogV30


__all__ = ["install", "PreferredLogV30"]
