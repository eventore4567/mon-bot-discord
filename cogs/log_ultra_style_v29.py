"""SentriX V29.4 — rendu cyber premium inspiré du mockup SentriX.

V27/V28 restent responsables de la déduplication, des IDs, de l'Audit Log et des
mentions silencieuses. Cette couche ne modifie que le rendu final Components V2.

Principes :
- identité visuelle SentriX cohérente ;
- fiche large et compacte ;
- auteur, salon et heure regroupés ;
- pour un message modifié : AVANT → APRÈS + bouton Voir le message ;
- barre d'IDs compacte en bas ;
- aucune notification malgré les vraies mentions Discord.
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
    "message_delete": "SUPPRESSION DÉTECTÉE",
    "message_edit": "ÉDITION DÉTECTÉE",
    "member_ban": "SANCTION ENREGISTRÉE",
    "member_unban": "ACCÈS RÉTABLI",
    "member_timeout": "RESTRICTION ACTIVE",
    "member_role_update": "PERMISSIONS MODIFIÉES",
    "channel_create": "SALON CRÉÉ",
    "channel_delete": "SALON SUPPRIMÉ",
    "channel_update": "SALON MODIFIÉ",
    "role_create": "RÔLE CRÉÉ",
    "role_delete": "RÔLE SUPPRIMÉ",
    "role_update": "RÔLE MODIFIÉ",
    "guild_update": "SERVEUR MODIFIÉ",
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
    category_icon = CATEGORY_ICON.get(str(log_type), SENTRIX_ICONS["event"])
    ts = _event_timestamp(embed)
    status = EVENT_STATUS.get(_event(log_type, embed), "ÉVÉNEMENT ENREGISTRÉ")
    text = (
        f"-# {SENTRIX_ICONS['brand']} SENTRIX  •  SECURE AUDIT  •  {category_icon} {category}\n"
        f"# {_event_title(log_type, embed)}\n"
        f"{SENTRIX_ICONS['signal']} **{status}**  ·  <t:{ts}:R>  ·  `LIVE`\n"
        f"-# {guild.name}  •  fiable  •  rapide  •  sécurisé"
    )[:3900]
    return discord.ui.TextDisplay(text), v28._avatar(bot, guild, embed)


def _identity_panel(guild: discord.Guild, embed: discord.Embed) -> str:
    author = _field_value(embed, "auteur", "membre", "utilisateur", "cible")
    actor = _field_value(embed, "effectue par", "moderateur", "acteur", "executant")
    channel = v28._resolved_channel(guild, embed)
    channel_raw = _field_value(embed, "salon", "channel")
    ts = _event_timestamp(embed)

    author_text = _mention(author) if author else "Non disponible"
    actor_text = _mention(actor) if actor else None
    salon_text = channel.mention if channel is not None else _plain_line(channel_raw, 180)

    lines = [
        f"### {SENTRIX_ICONS['watch']} IDENTITÉ   •   {SENTRIX_ICONS['signal']} SALON   •   {SENTRIX_ICONS['audit']} HEURE",
        f"**Auteur / cible**  {author_text}   •   **Salon**  {salon_text}   •   **Date**  <t:{ts}:t>",
    ]
    if actor_text:
        bot_tag = " `BOT`" if "bot" in v28._plain(actor) else ""
        lines.append(f"{SENTRIX_ICONS['action']} **Action par**  {actor_text}{bot_tag}")
    return "\n".join(lines)[:3900]


def _edit_panel(embed: discord.Embed) -> str | None:
    before = _field_value(embed, "avant")
    after = _field_value(embed, "apres")
    if not before and not after:
        return None

    before = str(before or "Non disponible")[:1100].replace("\n", "\n> ")
    after = str(after or "Non disponible")[:1100].replace("\n", "\n> ")
    return (
        f"### {SENTRIX_ICONS['change']} AVANT  ⟶  APRÈS\n"
        f"**AVANT**\n> {before}\n\n"
        f"**APRÈS**\n> {after}\n"
        f"-# {SENTRIX_ICONS['signal']} Changement détecté sur le contenu du message"
    )[:3900]


def _details_panel(embed: discord.Embed) -> str | None:
    if _is_role_batch(embed):
        text = (embed.description or "").strip()
        return f"### {SENTRIX_ICONS['action']} RÔLES REGROUPÉS\n{text[:3000]}" if text else None

    content = _field_value(embed, "contenu")
    reason = _field_value(embed, "raison", "raison audit log")
    duration = _field_value(embed, "duree", "fin du timeout", "nouvel etat")
    attachments = _field_value(embed, "pieces jointes", "pièces jointes")

    rows: list[str] = []
    if content:
        quoted = str(content)[:1300].replace("\n", "\n> ")
        rows.append(f"**{SENTRIX_ICONS['archive']} Contenu**\n> {quoted}")
    if reason:
        rows.append(f"**{SENTRIX_ICONS['secure']} Raison**  {_plain_line(reason, 500)}")
    if duration:
        rows.append(f"**{SENTRIX_ICONS['audit']} Durée / état**  {_plain_line(duration, 360)}")
    if attachments:
        rows.append(f"**{SENTRIX_ICONS['archive']} Pièces jointes**\n{str(attachments)[:750]}")
    if not rows:
        return None
    return f"### {SENTRIX_ICONS['archive']} DÉTAILS\n" + "\n\n".join(rows[:4])


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
        result.append((f"{SENTRIX_ICONS['event']} ID message", message_id))
    if channel is not None:
        result.append((f"{SENTRIX_ICONS['signal']} ID salon", channel.id))
    if author_id:
        result.append((f"{SENTRIX_ICONS['watch']} ID auteur", author_id))
    result.append((f"{SENTRIX_ICONS['brand']} ID serveur", guild.id))

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
                            description="SentriX audit identity",
                        ),
                    )
                )
            except Exception:
                container.add_item(header)
        else:
            container.add_item(header)

        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(_identity_panel(guild, clean)))

        edit_panel = _edit_panel(clean) if _event(log_type, clean) == "message_edit" else None
        if edit_panel:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(edit_panel))
        else:
            details = _details_panel(clean)
            if details:
                container.add_item(discord.ui.Separator())
                container.add_item(discord.ui.TextDisplay(details[:3900]))

        extras = v28._extra_blocks(clean)
        if extras and not edit_panel:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(extras[0][:1800]))

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

        footer = (
            f"-# {SENTRIX_ICONS['brand']} SentriX  •  Secure Audit  •  "
            f"{SENTRIX_ICONS['signal']} En ligne  •  fiable · rapide · sécurisé"
        )
        container.add_item(discord.ui.TextDisplay(footer))

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
