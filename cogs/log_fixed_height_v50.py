"""SentriX V50 — hauteur visuelle normalisée pour les journaux Discord.

Discord ne permet pas d'imposer une hauteur en pixels aux Components V2. Cette couche
utilise donc une structure strictement identique pour tous les logs, réserve un nombre
stable de lignes aux blocs CONTEXTE et DÉTAILS, puis tronque les contenus très longs.
Le résultat est une hauteur quasi identique sur desktop pour les logs courts et moyens,
sans toucher au routage, à l'Audit Log, à la déduplication ou aux permissions.
"""
from __future__ import annotations

import math
import re

import discord
from discord.ext import commands

from . import premium_logs_v2
from . import log_premium_v28 as v28
from . import log_preferred_style_v30 as v30
from .log_rectangle_v25 import _event_timestamp, _field_value, _is_role_batch, _target_id


ZWSP = "\u200b"
HEADER_DESCRIPTION_ROWS = 2
CONTEXT_ROWS = 2
DETAIL_ROWS = 5
ESTIMATED_CHARS_PER_ROW = 66

CATEGORY_LABELS = {
    "messages": ("💬", "MESSAGES"),
    "tickets": ("🎫", "TICKETS"),
    "moderation": ("🛡️", "MODÉRATION"),
    "voice": ("🔊", "VOCAL"),
    "server": ("⚙️", "SERVEUR"),
    "members": ("👥", "MEMBRES"),
    "roles": ("🏷️", "RÔLES"),
    "security": ("🛡️", "SÉCURITÉ"),
    "automod": ("🛡️", "SÉCURITÉ"),
    "economy": ("💳", "ÉCONOMIE"),
    "levels": ("📈", "NIVEAUX"),
    "ai": ("✨", "IA"),
    "games": ("🎮", "JEUX"),
    "system": ("🖥️", "SYSTÈME"),
    "channels": ("#️⃣", "SALONS"),
    "cases": ("📁", "DOSSIERS"),
    "spam": ("🛡️", "ANTI-SPAM"),
    "raid": ("🛡️", "ANTI-RAID"),
    "staff": ("🛡️", "STAFF"),
}

EVENT_STATUS = {
    "message_delete": "SUPPRESSION",
    "message_edit": "MODIFICATION",
    "member_ban": "BANNISSEMENT",
    "member_unban": "DÉBANNISSEMENT",
    "member_timeout": "TIMEOUT",
    "member_role_update": "RÔLES",
    "channel_create": "CRÉATION",
    "channel_delete": "SUPPRESSION",
    "channel_update": "MODIFICATION",
    "role_create": "CRÉATION",
    "role_delete": "SUPPRESSION",
    "role_update": "MODIFICATION",
    "guild_update": "MODIFICATION",
}

CONTEXT_TOKENS = {
    "auteur", "membre", "utilisateur", "cible", "salon", "channel",
    "effectue par", "effectué par", "moderateur", "modérateur", "acteur",
    "executant", "exécutant",
}


def _plain(value: object) -> str:
    text = str(value or "")
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _clip(value: object, limit: int, *, fallback: str = "Non disponible") -> str:
    text = _plain(value)
    if not text:
        return fallback
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _approx_rows(text: str, chars_per_row: int = ESTIMATED_CHARS_PER_ROW) -> int:
    rows = 0
    for line in (text.splitlines() or [""]):
        visible = re.sub(r"[*_`~>#|]", "", line)
        # Mentions et timestamps sont plus courts visuellement que leur source texte.
        visible = re.sub(r"<[@#&]!?(\d+)>", "mention", visible)
        visible = re.sub(r"<t:\d+(?::[A-Za-z])?>", "temps", visible)
        rows += max(1, math.ceil(max(1, len(visible)) / chars_per_row))
    return rows


def _pad_rows(text: str, target_rows: int) -> str:
    text = text.strip() or ZWSP
    rows = _approx_rows(text)
    if rows >= target_rows:
        return text
    return text + "\n" + "\n".join(ZWSP for _ in range(target_rows - rows))


def _title(log_type: str, embed: discord.Embed) -> str:
    title = v30._title(log_type, embed)
    # Un titre excessivement long ferait varier la hauteur même avec le padding.
    return _clip(title, 58, fallback="📋 Journal SentriX")


def _description(embed: discord.Embed) -> str:
    # ~125 caractères correspondent à environ deux lignes sur la carte desktop de référence.
    description = _clip(embed.description, 125, fallback="Événement enregistré automatiquement par SentriX.")
    return _pad_rows(description, HEADER_DESCRIPTION_ROWS)


def _mention_value(value: object, *, fallback: str = "Non disponible") -> str:
    raw = str(value or "")
    match = re.search(r"<@!?(\d{15,22})>", raw)
    if match:
        return f"<@{match.group(1)}>"
    uid = v28._first_id(raw)
    if uid:
        return f"<@{uid}>"
    return _clip(raw, 64, fallback=fallback)


def _channel_value(guild: discord.Guild, embed: discord.Embed) -> str:
    channel = v28._resolved_channel(guild, embed)
    if channel is not None:
        return channel.mention
    raw = _field_value(embed, "salon", "channel")
    channel_match = re.search(r"<#(\d{15,22})>", raw or "")
    if channel_match:
        return f"<#{channel_match.group(1)}>"
    return _clip(raw, 60)


def _target_value(embed: discord.Embed) -> str:
    raw = _field_value(embed, "auteur", "membre", "utilisateur", "cible")
    if not raw:
        target_id = _target_id(embed)
        if target_id:
            raw = f"<@{target_id}>"
    return _mention_value(raw)


def _context_block(guild: discord.Guild, embed: discord.Embed) -> str:
    # Toujours exactement les deux mêmes lignes principales : la hauteur ne dépend plus
    # du nombre d'informations disponibles dans l'événement.
    text = (
        f"**Salon**  {_channel_value(guild, embed)}\n"
        f"**Cible**  {_target_value(embed)}"
    )
    return _pad_rows(text, CONTEXT_ROWS)


def _is_context_field(name: str) -> bool:
    normalized = v30._norm(name)
    return any(token == normalized or token in normalized for token in CONTEXT_TOKENS)


def _detail_candidates(guild: discord.Guild, embed: discord.Embed) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []

    if _is_role_batch(embed):
        description = _clip(v30._restore_role_mentions(guild, embed.description or ""), 180)
        return [("Détails", description)]

    before = _field_value(embed, "avant")
    after = _field_value(embed, "apres")
    if before:
        result.append(("Avant", _clip(v30._restore_role_mentions(guild, before), 105)))
    if after and len(result) < 2:
        result.append(("Après", _clip(v30._restore_role_mentions(guild, after), 105)))

    for field in embed.fields:
        if len(result) >= 2:
            break
        name = str(field.name or "Information").strip() or "Information"
        if v30._is_id_field(name) or _is_context_field(name):
            continue
        normalized = v30._norm(name)
        if normalized in {"avant", "apres"}:
            continue
        value = str(field.value or "").strip()
        if not value:
            continue
        value = v30._restore_role_mentions(guild, value)
        clean_name = re.sub(r"^[^\wÀ-ÿ]+\s*", "", name).strip() or "Information"
        # Une ligne principale peut occuper ~2 lignes visuelles ; la seconde reste courte.
        if not result and any(token in normalized for token in ("contenu", "message", "raison")):
            limit = 135
        else:
            limit = 82
        result.append((clean_name, _clip(value, limit)))

    if not result:
        actor = _field_value(embed, "effectue par", "effectué par", "moderateur", "modérateur", "acteur")
        if actor:
            result.append(("Action par", _mention_value(actor)))

    if not result:
        result.append(("Information", "Aucun détail supplémentaire."))
    return result[:2]


def _details_block(guild: discord.Guild, embed: discord.Embed) -> str:
    rows: list[str] = []
    for label, value in _detail_candidates(guild, embed):
        rows.append(f"**{_clip(label, 28)}**  {value}")
    text = "\n".join(rows)

    # Cap strict : même un message de plusieurs milliers de caractères reste proche de
    # la hauteur de référence. Le texte complet existe toujours dans Discord lui-même.
    if len(text) > 295:
        text = text[:294].rstrip() + "…"
    return _pad_rows(text, DETAIL_ROWS)


def _avatar(bot: commands.Bot, guild: discord.Guild, embed: discord.Embed) -> str | None:
    try:
        avatar = v28._avatar(bot, guild, embed)
        if avatar:
            return str(avatar)
    except Exception:
        pass
    if bot.user:
        return str(bot.user.display_avatar.url)
    if guild.icon:
        return str(guild.icon.url)
    return None


def _button_set(guild: discord.Guild, log_type: str, embed: discord.Embed, inherited: list[tuple[str, int]]) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    used: set[int] = set()

    def add(label: str, value: int | None):
        if not value:
            return
        ivalue = int(value)
        if ivalue in used:
            return
        used.add(ivalue)
        result.append((label, ivalue))

    add("ID message", v28._message_id(log_type, embed))
    channel = v28._resolved_channel(guild, embed)
    add("ID salon", getattr(channel, "id", None))
    author = v28._first_id(_field_value(embed, "auteur", "membre", "utilisateur", "cible"))
    if author is None:
        author = _target_id(embed)
    add("ID auteur", author)
    add("ID serveur", guild.id)

    for label, value in inherited:
        try:
            add(str(label), int(value))
        except (TypeError, ValueError):
            continue
    return result[:4]


class FixedHeightLogV50(discord.ui.LayoutView):
    """Carte de log à structure fixe, visuellement stable entre événements."""

    _sentrix_log_layout = True
    _sentrix_fixed_height_v50 = True

    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        buttons: list[tuple[str, int]],
    ):
        super().__init__(timeout=6 * 60 * 60)

        clean = v28._silent_mention_embed(embed.copy())
        try:
            v28.v27._restore_channel_mentions(guild, clean)
        except Exception:
            pass
        clean = v28._ensure_message_id_field(log_type, clean)

        category_icon, category = CATEGORY_LABELS.get(
            str(log_type),
            ("📋", str(log_type).upper()),
        )
        event = v28._event(log_type, clean)
        status = EVENT_STATUS.get(event, "ÉVÉNEMENT")
        timestamp = _event_timestamp(clean)
        accent = v30._accent(log_type, clean)

        header_text = (
            f"-# ✦ SENTRIX / {category_icon} {category} / SECURE AUDIT\n\n"
            f"# {_title(log_type, clean)}\n"
            f"**{status}**  ·  <t:{timestamp}:R>  ·  `LIVE LOG`\n"
            f"{_description(clean)}"
        )[:3900]

        container = discord.ui.Container(accent_colour=accent)
        avatar = _avatar(bot, guild, clean)
        header = discord.ui.TextDisplay(header_text)
        if avatar:
            try:
                container.add_item(
                    discord.ui.Section(
                        header,
                        accessory=discord.ui.Thumbnail(avatar, description="SentriX Secure Audit"),
                    )
                )
            except Exception:
                container.add_item(header)
        else:
            container.add_item(header)

        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(
                "### CONTEXTE\n" + _context_block(guild, clean)
            )
        )

        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(
                "### DÉTAILS\n" + _details_block(guild, clean)
            )
        )

        final_buttons = _button_set(guild, log_type, clean, buttons)
        row = discord.ui.ActionRow()
        for index, (label, value) in enumerate(final_buttons):
            row.add_item(premium_logs_v2.CopyIdButton(label, int(value), index))
        if row.children:
            container.add_item(row)

        container.add_item(discord.ui.TextDisplay("-# SentriX • Secure Audit"))

        try:
            self._sentrix_log_fingerprint = v30._canonical_fingerprint(guild, log_type, clean)
        except Exception:
            self._sentrix_log_fingerprint = v28._fingerprint(guild, log_type, clean)
        self._sentrix_is_log_layout = True
        self.add_item(container)


def install(bot: commands.Bot | None = None, extension_name: str = "") -> None:
    """Remplace uniquement le renderer visuel final ; aucun nouveau listener/commande."""
    del bot, extension_name
    required = ("LayoutView", "Container", "Section", "TextDisplay", "Thumbnail", "Separator")
    if not all(hasattr(discord.ui, name) for name in required):
        return
    premium_logs_v2.PremiumLogLayout = FixedHeightLogV50


__all__ = ["install", "FixedHeightLogV50"]
