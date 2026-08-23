"""SentriX V30 — style unique pour tous les journaux.

V27/V28 gardent la déduplication, l'Audit Log, les IDs et les mentions silencieuses.
V30 applique le même rendu visuel à messages, tickets, modération, vocal et serveur :
un gros titre, CONTEXTE, DÉTAILS, avatar à droite et boutons d'IDs en bas.
"""
from __future__ import annotations

import re

import discord
from discord.ext import commands

from . import premium_logs_v2
from . import log_premium_v28 as v28
from .log_rectangle_v25 import _event_timestamp, _field_value, _is_role_batch


CATEGORY_ICON = {
    "messages": "💬",
    "tickets": "🎫",
    "moderation": "🛡️",
    "voice": "🔊",
    "server": "⚙️",
    "members": "👤",
    "roles": "⚙️",
    "security": "🛡️",
    "automod": "🛡️",
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

EVENT_ICON = {
    "message_delete": "🗑️",
    "message_edit": "✏️",
    "member_ban": "🔨",
    "member_unban": "🔓",
    "member_timeout": "⏱️",
    "member_role_update": "⚙️",
    "channel_create": "⚙️",
    "channel_delete": "⚙️",
    "channel_update": "⚙️",
    "role_create": "⚙️",
    "role_delete": "⚙️",
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

CONTEXT_NAMES = {
    "salon", "channel", "auteur", "membre", "utilisateur", "cible",
    "effectue par", "effectué par", "moderateur", "modérateur", "acteur", "executant", "exécutant",
}
ID_NAMES = {
    "id", "id message", "id du message", "identifiant du message", "id salon", "id serveur",
    "id auteur", "id membre", "id cible", "identifiant",
}


def _event(log_type: str, embed: discord.Embed) -> str:
    return v28._event(log_type, embed)


def _norm(value: str | None) -> str:
    text = str(value or "").casefold()
    for old, new in (("é", "e"), ("è", "e"), ("ê", "e"), ("à", "a"), ("ù", "u"), ("ô", "o"), ("î", "i"), ("ç", "c")):
        text = text.replace(old, new)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _plain(value: str | None, limit: int = 500) -> str:
    text = str(value or "").strip() or "Non disponible"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _mention(value: str | None) -> str:
    uid = v28._first_id(value)
    return f"<@{uid}>" if uid else _plain(value, 240)


def _accent(log_type: str, embed: discord.Embed) -> int:
    event = _event(log_type, embed)
    if event in EVENT_ACCENTS:
        return EVENT_ACCENTS[event]
    if embed.colour:
        return int(embed.colour.value)
    return {
        "tickets": 0x5865F2,
        "moderation": 0xED4245,
        "voice": 0x3498DB,
        "server": 0x7C5CFC,
    }.get(str(log_type), 0x7C5CFC)


def _generic_status(embed: discord.Embed) -> str:
    text = _norm(f"{embed.title or ''} {embed.description or ''}")
    if any(word in text for word in ("supprime", "ferme", "deconnexion", "quitte", "retire", "ban", "kick")):
        return "SUPPRESSION" if "supprime" in text else "ACTION"
    if any(word in text for word in ("ouvert", "cree", "connexion", "rejoint", "ajoute")):
        return "CRÉATION" if "cree" in text else "ACTION"
    if any(word in text for word in ("modifie", "change", "deplace", "claim")):
        return "MODIFICATION"
    return "ÉVÉNEMENT"


def _title(log_type: str, embed: discord.Embed) -> str:
    raw = re.sub(r"\s+", " ", str(embed.title or "Journal SentriX")).strip()
    raw = re.sub(r"^[^\wÀ-ÿ]+\s*", "", raw).strip() or "Journal SentriX"
    icon = EVENT_ICON.get(_event(log_type, embed)) or CATEGORY_ICON.get(str(log_type), "")
    return f"{icon} {raw}".strip()


def _header(bot: commands.Bot, guild: discord.Guild, log_type: str, embed: discord.Embed):
    category, _ = v28._category(log_type)
    event = _event(log_type, embed)
    status = EVENT_STATUS.get(event, _generic_status(embed))
    ts = _event_timestamp(embed)
    category_icon = CATEGORY_ICON.get(str(log_type), "")
    summary = (embed.description or "").strip() or v28._summary(log_type, embed)
    text = (
        f"-# ✦ SENTRIX  /  {category_icon} {category}  /  SECURE AUDIT\n\n"
        f"# {_title(log_type, embed)}\n"
        f"**{status}**  ·  <t:{ts}:R>  ·  `LIVE LOG`\n"
        f"{summary[:800]}"
    )[:3900]
    return discord.ui.TextDisplay(text), v28._avatar(bot, guild, embed)


def _context(guild: discord.Guild, embed: discord.Embed) -> tuple[str, set[int]]:
    channel = v28._resolved_channel(guild, embed)
    channel_raw = _field_value(embed, "salon", "channel")
    target = _field_value(embed, "auteur", "membre", "utilisateur", "cible")
    actor = _field_value(embed, "effectue par", "effectué par", "moderateur", "modérateur", "acteur", "executant", "exécutant")
    rows: list[str] = []
    consumed: set[int] = set()

    for index, field in enumerate(embed.fields):
        name = _norm(str(field.name))
        if any(token == name or token in name for token in CONTEXT_NAMES):
            consumed.add(index)

    if channel is not None:
        rows.append(f"**Salon**  {channel.mention}")
    elif channel_raw:
        rows.append(f"**Salon**  {_plain(channel_raw, 300)}")
    if target:
        rows.append(f"**Cible**  {_mention(target)}")
    if actor:
        bot_tag = "  `BOT`" if "bot" in _norm(actor) else ""
        rows.append(f"**Action par**  {_mention(actor)}{bot_tag}")
    if not rows:
        rows.append(f"**Serveur**  {discord.utils.escape_markdown(guild.name)}")
    return "### CONTEXTE\n" + "\n".join(f"> {row}" for row in rows[:4]), consumed


def _is_id_field(name: str) -> bool:
    normalized = _norm(name)
    return normalized in {_norm(item) for item in ID_NAMES} or normalized.startswith("id ") or normalized.startswith("identifiant ")


def _generic_details(embed: discord.Embed, consumed: set[int]) -> str | None:
    if _is_role_batch(embed):
        text = (embed.description or "").strip()
        return f"### DÉTAILS\n{text[:3200]}" if text else None

    rows: list[str] = []
    before = _field_value(embed, "avant")
    after = _field_value(embed, "apres")
    if before or after:
        if before:
            rows.append(f"**Avant**\n> {str(before)[:900].replace(chr(10), chr(10) + '> ')}")
        if after:
            rows.append(f"**Après**\n> {str(after)[:900].replace(chr(10), chr(10) + '> ')}")

    for index, field in enumerate(embed.fields):
        if index in consumed:
            continue
        name = str(field.name).strip() or "Information"
        normalized = _norm(name)
        if _is_id_field(name) or normalized in {"avant", "apres"}:
            continue
        value = str(field.value).strip()
        if not value:
            continue
        clean_name = re.sub(r"^[^\wÀ-ÿ]+\s*", "", name).strip() or "Information"
        if len(value) > 850:
            value = value[:849] + "…"
        if "\n" in value or len(value) > 120:
            quoted = value.replace("\n", "\n> ")
            rows.append(f"**{clean_name}**\n> {quoted}")
        else:
            rows.append(f"**{clean_name}**  {value}")
        if len(rows) >= 6:
            break

    if not rows:
        return None
    return "### DÉTAILS\n" + "\n\n".join(rows)[:3500]


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
        result.append(("ID message", message_id))
    if channel is not None:
        result.append(("ID salon", channel.id))
    if author_id:
        result.append(("ID auteur", author_id))
    result.append(("ID serveur", guild.id))
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
                container.add_item(discord.ui.Section(header, accessory=discord.ui.Thumbnail(avatar, description="SentriX audit")))
            except Exception:
                container.add_item(header)
        else:
            container.add_item(header)

        container.add_item(discord.ui.Separator())
        context, consumed = _context(guild, clean)
        container.add_item(discord.ui.TextDisplay(context[:3900]))

        body = _generic_details(clean, consumed)
        if body:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(body[:3900]))

        jump_url = _message_jump_url(guild, log_type, clean)
        ids = _id_buttons(guild, log_type, clean)
        if jump_url or ids:
            row = discord.ui.ActionRow()
            if jump_url:
                row.add_item(discord.ui.Button(label="Voir le message", emoji="🔗", style=discord.ButtonStyle.link, url=jump_url))
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
