"""SentriX — renderer final des logs, format large et compact.

Tous les journaux conservent les mêmes données, le même routage, la déduplication et les
permissions existantes. Seule la présentation change : pas de bannière, pas d'emoji
décoratif, un cadre Components V2 large, des séparateurs nets et les informations utiles
sur peu de lignes.
"""
from __future__ import annotations

import re

import discord
from discord.ext import commands

from . import premium_logs_v2
from . import log_premium_v28 as v28
from . import log_preferred_style_v30 as v30
from .log_rectangle_v25 import _event_timestamp, _field_value, _is_role_batch, _target_id


BAR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

CATEGORY_LABELS = {
    "messages": "MESSAGES",
    "tickets": "TICKETS",
    "moderation": "MODÉRATION",
    "voice": "VOCAL",
    "server": "SERVEUR",
    "members": "MEMBRES",
    "roles": "RÔLES",
    "security": "SÉCURITÉ",
    "automod": "SÉCURITÉ",
    "economy": "ÉCONOMIE",
    "levels": "NIVEAUX",
    "ai": "IA",
    "games": "JEUX",
    "system": "SYSTÈME",
    "channels": "SALONS",
    "cases": "DOSSIERS",
    "spam": "ANTI-SPAM",
    "raid": "ANTI-RAID",
    "staff": "STAFF",
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
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _clip(value: object, limit: int, *, fallback: str = "Non disponible") -> str:
    text = _plain(value)
    if not text:
        return fallback
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _clean_heading(value: object, *, fallback: str) -> str:
    text = _plain(value)
    # Retire uniquement les décorations placées devant le texte ; le contenu métier du
    # log (y compris les emojis réellement écrits par un membre) reste intact.
    text = re.sub(r"^[^A-Za-zÀ-ÿ0-9@#<]+", "", text).strip()
    return _clip(text, 64, fallback=fallback)


def _title(log_type: str, embed: discord.Embed) -> str:
    return _clean_heading(v30._title(log_type, embed), fallback="Journal SentriX")


def _description(embed: discord.Embed) -> str:
    return _clip(
        embed.description,
        190,
        fallback="Événement enregistré automatiquement par SentriX.",
    )


def _mention_value(value: object, *, fallback: str = "Non disponible") -> str:
    raw = str(value or "")
    match = re.search(r"<@!?(\d{15,22})>", raw)
    if match:
        return f"<@{match.group(1)}>"
    uid = v28._first_id(raw)
    if uid:
        return f"<@{uid}>"
    return _clip(raw, 58, fallback=fallback)


def _channel_value(guild: discord.Guild, embed: discord.Embed) -> str:
    channel = v28._resolved_channel(guild, embed)
    if channel is not None:
        return channel.mention
    raw = _field_value(embed, "salon", "channel")
    match = re.search(r"<#(\d{15,22})>", raw or "")
    if match:
        return f"<#{match.group(1)}>"
    return _clip(raw, 58)


def _target_value(embed: discord.Embed) -> str:
    raw = _field_value(embed, "auteur", "membre", "utilisateur", "cible")
    if not raw:
        target_id = _target_id(embed)
        if target_id:
            raw = f"<@{target_id}>"
    return _mention_value(raw)


def _actor_value(embed: discord.Embed) -> str:
    raw = _field_value(
        embed,
        "effectue par", "effectué par", "moderateur", "modérateur", "acteur",
        "executant", "exécutant",
    )
    return _mention_value(raw, fallback="Automatique")


def _context_block(guild: discord.Guild, embed: discord.Embed) -> str:
    return (
        f"**Salon**  {_channel_value(guild, embed)}   •   "
        f"**Cible**  {_target_value(embed)}   •   "
        f"**Action par**  {_actor_value(embed)}"
    )


def _is_context_field(name: str) -> bool:
    normalized = v30._norm(name)
    return any(token == normalized or token in normalized for token in CONTEXT_TOKENS)


def _detail_candidates(guild: discord.Guild, embed: discord.Embed) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []

    if _is_role_batch(embed):
        value = _clip(v30._restore_role_mentions(guild, embed.description or ""), 210)
        return [("Détails", value)]

    before = _field_value(embed, "avant")
    after = _field_value(embed, "apres")
    if before:
        result.append(("Avant", _clip(v30._restore_role_mentions(guild, before), 120)))
    if after:
        result.append(("Après", _clip(v30._restore_role_mentions(guild, after), 120)))

    for field in embed.fields:
        if len(result) >= 3:
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
        clean_name = _clean_heading(name, fallback="Information")
        limit = 170 if any(token in normalized for token in ("contenu", "message", "raison")) else 105
        result.append((clean_name, _clip(value, limit)))

    if not result:
        result.append(("Information", "Aucun détail supplémentaire."))
    return result[:3]


def _details_block(guild: discord.Guild, embed: discord.Embed) -> str:
    rows = [f"**{_clip(label, 26)}**  {value}" for label, value in _detail_candidates(guild, embed)]
    text = "\n".join(rows)
    return _clip(text, 430, fallback="Aucun détail supplémentaire.")


def _button_set(
    guild: discord.Guild,
    log_type: str,
    embed: discord.Embed,
    inherited: list[tuple[str, int]],
) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    used: set[int] = set()

    def add(label: str, value: int | None) -> None:
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
    """Renderer compatible V50, désormais en carte large SentriX sans décoration inutile."""

    _sentrix_log_layout = True
    _sentrix_fixed_height_v50 = True
    _sentrix_wide_log_v4 = True

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

        category = CATEGORY_LABELS.get(str(log_type), str(log_type).upper())
        event = v28._event(log_type, clean)
        status = EVENT_STATUS.get(event, "ÉVÉNEMENT")
        timestamp = _event_timestamp(clean)
        accent = v30._accent(log_type, clean)

        header_text = (
            f"-# SENTRIX / {category} / LIVE AUDIT\n"
            f"# {_title(log_type, clean)}\n"
            f"**{status}**   •   <t:{timestamp}:R>   •   `{category}`\n"
            f"{BAR}\n"
            f"{_description(clean)}"
        )[:3900]

        container = discord.ui.Container(accent_colour=accent)
        container.add_item(discord.ui.TextDisplay(header_text))
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(
            discord.ui.TextDisplay(
                "**CONTEXTE**\n" + _context_block(guild, clean)
            )
        )
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(
            discord.ui.TextDisplay(
                "**DÉTAILS**\n" + _details_block(guild, clean)
            )
        )

        final_buttons = _button_set(guild, log_type, clean, buttons)
        row = discord.ui.ActionRow()
        for index, (label, value) in enumerate(final_buttons):
            button = premium_logs_v2.CopyIdButton(label, int(value), index)
            try:
                button.emoji = None
            except Exception:
                pass
            row.add_item(button)
        if row.children:
            container.add_item(row)

        container.add_item(discord.ui.TextDisplay("-# SentriX • Journal sécurisé"))

        try:
            self._sentrix_log_fingerprint = v30._canonical_fingerprint(guild, log_type, clean)
        except Exception:
            self._sentrix_log_fingerprint = v28._fingerprint(guild, log_type, clean)
        self._sentrix_is_log_layout = True
        self.add_item(container)


def install(bot: commands.Bot | None = None, extension_name: str = "") -> None:
    """Remplace uniquement le renderer visuel final ; aucun listener n'est ajouté."""
    del bot, extension_name
    required = ("LayoutView", "Container", "TextDisplay", "Separator")
    if not all(hasattr(discord.ui, name) for name in required):
        return
    premium_logs_v2.PremiumLogLayout = FixedHeightLogV50


__all__ = ["install", "FixedHeightLogV50"]
