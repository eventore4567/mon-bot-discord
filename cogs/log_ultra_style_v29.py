"""SentriX V29 — rendu Ultra Premium compact des journaux.

V29 ne remplace aucune logique de sécurité : V27/V28 gardent la déduplication, les IDs,
l'Audit Log et les mentions silencieuses. Cette couche reprend seulement le renderer final
avec une identité visuelle SentriX cohérente.

V29.3 :
- palette de 10 icônes SentriX cohérentes ;
- anciens emojis disparates remplacés ;
- bouton lien ``Voir le message`` conservé pour les messages modifiés ;
- rendu compact et uniforme.
"""
from __future__ import annotations

import re

import discord
from discord.ext import commands

from . import premium_logs_v2
from . import log_premium_v28 as v28
from .log_rectangle_v25 import _event_timestamp, _field_value, _is_role_batch


# Palette officielle SentriX utilisée dans toute la fiche.
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

CATEGORY_ICON = {
    "messages": SENTRIX_ICONS["event"],
    "members": SENTRIX_ICONS["watch"],
    "roles": SENTRIX_ICONS["action"],
    "server": SENTRIX_ICONS["audit"],
    "voice": SENTRIX_ICONS["signal"],
    "moderation": SENTRIX_ICONS["brand"],
    "automod": SENTRIX_ICONS["secure"],
    "security": SENTRIX_ICONS["secure"],
    "tickets": SENTRIX_ICONS["archive"],
    "economy": SENTRIX_ICONS["event"],
    "levels": SENTRIX_ICONS["signal"],
    "ai": SENTRIX_ICONS["change"],
    "games": SENTRIX_ICONS["event"],
    "system": SENTRIX_ICONS["audit"],
}

EVENT_ICON = {
    "message_delete": SENTRIX_ICONS["archive"],
    "message_edit": SENTRIX_ICONS["change"],
    "member_ban": SENTRIX_ICONS["secure"],
    "member_unban": SENTRIX_ICONS["signal"],
    "member_timeout": SENTRIX_ICONS["watch"],
    "member_role_update": SENTRIX_ICONS["action"],
    "channel_create": SENTRIX_ICONS["signal"],
    "channel_delete": SENTRIX_ICONS["archive"],
    "channel_update": SENTRIX_ICONS["audit"],
    "role_create": SENTRIX_ICONS["event"],
    "role_delete": SENTRIX_ICONS["archive"],
    "role_update": SENTRIX_ICONS["action"],
    "guild_update": SENTRIX_ICONS["audit"],
}

EVENT_ACCENTS = {
    "message_delete": 0xED4245,
    "message_edit": 0xF0B232,
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


def _safe_one_line(value: str | None, limit: int = 320) -> str:
    text = re.sub(r"\s*\n\s*", "  ·  ", str(value or "").strip())
    text = re.sub(r"\s{2,}", " ", text)
    return (text if text else "Non disponible")[:limit]


def _user_mention(value: str | None) -> str:
    uid = v28._first_id(value)
    return f"<@{uid}>" if uid else _safe_one_line(value, 220)


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


def _status(log_type: str, embed: discord.Embed) -> str:
    return EVENT_STATUS.get(_event(log_type, embed), "ÉVÉNEMENT")


def _clean_event_title(log_type: str, embed: discord.Embed) -> str:
    raw = re.sub(r"\s+", " ", str(embed.title or "Journal SentriX")).strip()
    # Retire l'ancien emoji éventuel afin d'éviter deux styles en même temps.
    raw = re.sub(r"^[^\wÀ-ÿ]+\s*", "", raw).strip() or "Journal SentriX"
    icon = EVENT_ICON.get(_event(log_type, embed), SENTRIX_ICONS["event"])
    return f"{icon} {raw}"


def _context(guild: discord.Guild, embed: discord.Embed) -> str:
    channel = v28._resolved_channel(guild, embed)
    channel_raw = _field_value(embed, "salon", "channel")
    target = _field_value(embed, "auteur", "membre", "utilisateur", "cible")
    actor = _field_value(embed, "effectue par", "moderateur", "acteur", "executant")

    rows: list[str] = []
    if channel is not None:
        rows.append(f"{SENTRIX_ICONS['signal']} **Salon**  {channel.mention}")
    elif channel_raw:
        rows.append(f"{SENTRIX_ICONS['signal']} **Salon**  {_safe_one_line(channel_raw, 260)}")
    if target:
        rows.append(f"{SENTRIX_ICONS['watch']} **Cible**  {_user_mention(target)}")
    if actor:
        bot_tag = "  `BOT`" if "bot" in v28._plain(actor) else ""
        rows.append(f"{SENTRIX_ICONS['action']} **Action par**  {_user_mention(actor)}{bot_tag}")
    if not rows:
        rows.append(f"{SENTRIX_ICONS['audit']} **Serveur**  **{discord.utils.escape_markdown(guild.name)}**")
    return f"### {SENTRIX_ICONS['watch']} CONTEXTE\n" + "\n".join(f"> {row}" for row in rows[:3])


def _payload(embed: discord.Embed) -> str | None:
    if _is_role_batch(embed):
        text = (embed.description or "").strip()
        return f"### {SENTRIX_ICONS['action']} RÔLES REGROUPÉS\n{text[:2800]}" if text else None

    content = _field_value(embed, "contenu")
    before = _field_value(embed, "avant")
    after = _field_value(embed, "apres")
    reason = _field_value(embed, "raison", "raison audit log")
    duration = _field_value(embed, "duree", "fin du timeout", "nouvel etat")
    attachments = _field_value(embed, "pieces jointes", "pièces jointes")

    rows: list[str] = []
    if content:
        quoted = str(content)[:1100].replace("\n", "\n> ")
        rows.append(f"**{SENTRIX_ICONS['archive']} Contenu**\n> {quoted}")
    if before:
        rows.append(f"**{SENTRIX_ICONS['watch']} Avant**\n> {str(before)[:700].replace(chr(10), chr(10) + '> ')}")
    if after:
        rows.append(f"**{SENTRIX_ICONS['change']} Après**\n> {str(after)[:700].replace(chr(10), chr(10) + '> ')}")
    if reason:
        rows.append(f"**{SENTRIX_ICONS['secure']} Raison**  {_safe_one_line(reason, 400)}")
    if duration:
        rows.append(f"**{SENTRIX_ICONS['audit']} Durée / état**  {_safe_one_line(duration, 300)}")
    if attachments:
        rows.append(f"**{SENTRIX_ICONS['archive']} Pièces jointes**\n{str(attachments)[:650]}")
    if not rows:
        return None
    return f"### {SENTRIX_ICONS['archive']} DÉTAILS\n" + "\n\n".join(rows[:4])


def _header(bot: commands.Bot, guild: discord.Guild, log_type: str, embed: discord.Embed) -> tuple[discord.ui.TextDisplay, str | None]:
    category, _ = v28._category(log_type)
    category_icon = CATEGORY_ICON.get(str(log_type), SENTRIX_ICONS["event"])
    status = _status(log_type, embed)
    ts = _event_timestamp(embed)
    text = (
        f"-# {SENTRIX_ICONS['brand']} SENTRIX  •  {category_icon} {category}  •  {guild.name}\n"
        f"# {_clean_event_title(log_type, embed)}\n"
        f"{SENTRIX_ICONS['signal']} **{status}**  ·  <t:{ts}:R>  ·  `SENTRIX LIVE`\n"
        f"{v28._summary(log_type, embed)}"
    )[:3900]
    return discord.ui.TextDisplay(text), v28._avatar(bot, guild, embed)


def _button_set(guild: discord.Guild, log_type: str, embed: discord.Embed, inherited: list[tuple[str, int]]) -> list[tuple[str, int]]:
    base = v28._buttons(guild, log_type, embed, inherited)
    server_pair = ("ID serveur", int(guild.id))
    priorities = ("message", "salon", "auteur", "serveur", "moderateur", "modérateur", "acteur")
    candidates = list(base)
    if all(int(value) != guild.id for _, value in candidates):
        candidates.append(server_pair)

    ordered: list[tuple[str, int]] = []
    used_values: set[int] = set()
    for token in priorities:
        for label, value in candidates:
            ivalue = int(value)
            if ivalue in used_values or token not in v28._plain(str(label)):
                continue
            clean_label = str(label).replace("Copier ", "")
            ordered.append((clean_label, ivalue))
            used_values.add(ivalue)
            break
    for label, value in candidates:
        ivalue = int(value)
        if ivalue in used_values:
            continue
        ordered.append((str(label).replace("Copier ", ""), ivalue))
        used_values.add(ivalue)
    return ordered[:4]


def _message_jump_url(guild: discord.Guild, log_type: str, embed: discord.Embed) -> str | None:
    if _event(log_type, embed) != "message_edit":
        return None
    message_id = v28._message_id(log_type, embed)
    channel = v28._resolved_channel(guild, embed)
    if not message_id or channel is None:
        return None
    return f"https://discord.com/channels/{guild.id}/{channel.id}/{message_id}"


class UltraPremiumLogV29(discord.ui.LayoutView):
    _sentrix_log_layout = True
    _sentrix_rectangle_v25 = True
    _sentrix_reference_v26 = True
    _sentrix_unified_v27 = True
    _sentrix_premium_v28 = True
    _sentrix_ultra_v29 = True

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
                    accessory=discord.ui.Thumbnail(avatar, description="SentriX audit identity"),
                ))
            except Exception:
                container.add_item(header)
        else:
            container.add_item(header)

        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(_context(guild, clean)[:3900]))

        payload = _payload(clean)
        if payload:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(payload[:3900]))

        extras = v28._extra_blocks(clean)
        if extras:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(extras[0][:2400]))

        jump_url = _message_jump_url(guild, log_type, clean)
        final_buttons = _button_set(guild, log_type, clean, buttons)
        if jump_url or final_buttons:
            row = discord.ui.ActionRow()
            if jump_url:
                row.add_item(discord.ui.Button(
                    label="Voir le message",
                    emoji=SENTRIX_ICONS["jump"],
                    style=discord.ButtonStyle.link,
                    url=jump_url,
                ))
            for index, (label, value) in enumerate(final_buttons[:4]):
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
    premium_logs_v2.PremiumLogLayout = UltraPremiumLogV29


__all__ = ["install", "UltraPremiumLogV29", "SENTRIX_ICONS"]
