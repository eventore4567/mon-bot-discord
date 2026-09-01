"""SentriX V28 — cartes de logs premium, larges et cohérentes.

Cette couche améliore uniquement le rendu final et ajoute une garde précise par ID de
message. V27 reste responsable de la normalisation des événements et de l'enrichissement
Audit Log ; V28 conserve ces garanties et ajoute :
- ID du message visible pour suppressions/modifications ;
- déduplication secondaire exacte par message_id ;
- vraie zone Contexte / Action / Données / Traçabilité ;
- salon cliquable conservé ;
- vraies mentions Discord membres/bots/rôles conservées, avec AllowedMentions.none() au
  dernier envoi pour qu'elles soient cliquables sans envoyer de notification ;
- champs inconnus conservés pour que tickets, vocal, économie, jeux, sécurité, etc. ne
  perdent aucune information ;
- boutons de copie d'ID cohérents.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time

import discord
from discord.ext import commands

from utils import log_service
from . import premium_logs_v2
from .log_rectangle_v25 import (
    CATEGORY_LABELS,
    _event_timestamp,
    _field_value,
    _is_role_batch,
    _target_id,
)
from . import log_single_pipeline_v27 as v27

logger = logging.getLogger("bot.log-premium-v28")
_SOURCE_INSTALLED = False
_RENDER_INSTALLED = False
_MESSAGE_TTL = 15.0
_MESSAGE_RECENT: dict[str, float] = {}

CATEGORY_META = {
    "messages": ("MESSAGES", "💬"),
    "members": ("MEMBRES", "👥"),
    "roles": ("RÔLES", "🏷️"),
    "server": ("SERVEUR", "⚙️"),
    "voice": ("VOCAL", "🎙️"),
    "moderation": ("MODÉRATION", "🛡️"),
    "automod": ("SÉCURITÉ", "🔒"),
    "security": ("SÉCURITÉ", "🔒"),
    "tickets": ("TICKETS", "🎫"),
    "economy": ("ÉCONOMIE", "💳"),
    "levels": ("NIVEAUX", "📈"),
    "ai": ("IA", "✨"),
    "games": ("JEUX", "🎮"),
    "system": ("SYSTÈME", "🖥️"),
}

EVENT_EMOJI = {
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

SUMMARY_BY_EVENT = {
    "message_delete": "Un message a été supprimé. SentriX a conservé son contexte et sa traçabilité.",
    "message_edit": "Un message a été modifié. Les valeurs avant et après sont conservées ci-dessous.",
    "member_ban": "Une action de bannissement a été enregistrée et rapprochée de l'Audit Log Discord.",
    "member_unban": "Une action de débannissement a été enregistrée et rapprochée de l'Audit Log Discord.",
    "member_timeout": "Un changement de timeout a été détecté sur ce membre.",
    "member_role_update": "Les rôles d'un membre ont changé. Les détails disponibles sont conservés.",
    "channel_create": "Un salon a été créé sur le serveur.",
    "channel_delete": "Un salon a été supprimé du serveur.",
    "channel_update": "La configuration d'un salon a été modifiée.",
    "role_create": "Un rôle a été créé sur le serveur.",
    "role_delete": "Un rôle a été supprimé du serveur.",
    "role_update": "La configuration d'un rôle a été modifiée.",
    "guild_update": "Une propriété du serveur a été modifiée.",
}

KNOWN_FIELD_MARKERS = (
    "auteur", "membre", "utilisateur", "cible", "salon", "channel",
    "contenu", "avant", "apres", "effectue par", "moderateur", "acteur",
    "raison", "duree", "fin du timeout", "nouvel etat", "id du message",
)


def _plain(value: str | None) -> str:
    return v27._plain(value)


def _first_id(value: str | None) -> int | None:
    return v27._first_id(value)


def _silent_mention_embed(source: discord.Embed) -> discord.Embed:
    """Conserve les vraies mentions Discord sans autoriser leur notification.

    Le garde de sortie V25 impose ``AllowedMentions.none()`` pour toutes les cartes de
    logs. On peut donc garder ``<@id>``, ``<@&id>`` et ``<#id>`` pour que Discord affiche
    de vraies mentions cliquables, sans ping. ``@everyone``/``@here`` sont neutralisés
    explicitement car ils n'apportent rien à un journal d'audit.
    """
    embed = source.copy()

    def safe(value: str | None, limit: int) -> str:
        text = str(value or "")
        text = text.replace("@everyone", "＠everyone").replace("@here", "＠here")
        return text[:limit]

    if embed.title:
        embed.title = safe(embed.title, 256)
    if embed.description:
        embed.description = safe(embed.description, 4096)
    for index, field in enumerate(list(embed.fields)):
        embed.set_field_at(
            index,
            name=safe(str(field.name), 256),
            value=safe(str(field.value), 1024),
            inline=False,
        )
    return embed


def _one_line(value: str | None, limit: int = 300) -> str:
    text = re.sub(r"\s*\n\s*", " · ", str(value or "").strip())
    text = re.sub(r"\s{2,}", " ", text)
    if not text:
        return "Non disponible"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _real_user_mention(value: str | None, *, with_id: bool = False) -> str:
    """Retourne une vraie mention <@id> si un snowflake utilisateur est disponible."""
    raw = str(value or "").strip()
    user_id = _first_id(raw)
    if not user_id:
        return _one_line(raw, 260)
    mention = f"<@{user_id}>"
    if with_id:
        return f"{mention} · `{user_id}`"
    return mention


def _event(log_type: str, embed: discord.Embed) -> str:
    return v27._event_kind(str(log_type), embed)


def _message_id(log_type: str, embed: discord.Embed) -> int | None:
    event = _event(log_type, embed)
    if event not in {"message_delete", "message_edit"}:
        return None
    explicit = _first_id(_field_value(embed, "id du message", "message id", "id message"))
    return explicit or _target_id(embed)


def _message_key(guild: discord.Guild, log_type: str, embed: discord.Embed) -> str | None:
    message_id = _message_id(log_type, embed)
    if message_id:
        return f"{guild.id}:{_event(log_type, embed)}:message:{message_id}"
    return None


def _remember_message(key: str) -> bool:
    now = time.monotonic()
    for item, expiry in list(_MESSAGE_RECENT.items())[:2000]:
        if expiry <= now:
            _MESSAGE_RECENT.pop(item, None)
    if _MESSAGE_RECENT.get(key, 0.0) > now:
        return False
    _MESSAGE_RECENT[key] = now + _MESSAGE_TTL
    return True


def _ensure_message_id_field(log_type: str, source: discord.Embed) -> discord.Embed:
    message_id = _message_id(log_type, source)
    if not message_id:
        return source
    for field in source.fields:
        if "id du message" in _plain(str(field.name)) or "message id" in _plain(str(field.name)):
            return source
    embed = source.copy()
    embed.add_field(name="ID du message", value=f"`{message_id}`", inline=False)
    return embed


def install_source_guard(bot: commands.Bot) -> None:
    """Seconde garde, basée sur le vrai message_id quand il existe."""
    del bot
    global _SOURCE_INSTALLED
    if _SOURCE_INSTALLED:
        return

    previous = log_service.send_log
    if getattr(previous, "_sentrix_premium_v28_source", False):
        _SOURCE_INSTALLED = True
        return

    async def send_with_message_identity(
        inner_bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        file: discord.File | None = None,
    
        **identity,
    ) -> bool:
        enriched = _ensure_message_id_field(str(log_type), embed)
        key = _message_key(guild, str(log_type), enriched)
        if key is not None and not _remember_message(key):
            logger.debug("V28 : doublon exact message bloqué guild=%s key=%s", guild.id, key)
            return True
        return await previous(inner_bot, guild, log_type, enriched, file=file, **identity)

    send_with_message_identity._sentrix_premium_v28_source = True
    send_with_message_identity._sentrix_original = previous
    log_service.send_log = send_with_message_identity
    _SOURCE_INSTALLED = True


def _category(log_type: str) -> tuple[str, str]:
    return CATEGORY_META.get(
        str(log_type),
        (CATEGORY_LABELS.get(str(log_type), str(log_type).upper()), "📋"),
    )


def _title(log_type: str, embed: discord.Embed) -> str:
    event = _event(log_type, embed)
    raw = re.sub(r"\s+", " ", str(embed.title or "Journal SentriX")).strip()
    emoji = EVENT_EMOJI.get(event, _category(log_type)[1])
    known_emoji_prefix = re.match(r"^[^\w\s]+\s*", raw)
    if known_emoji_prefix:
        raw = raw[known_emoji_prefix.end():].strip() or "Journal SentriX"
    return f"{emoji} {raw}"


def _summary(log_type: str, embed: discord.Embed) -> str:
    event = _event(log_type, embed)
    if event in SUMMARY_BY_EVENT:
        return SUMMARY_BY_EVENT[event]
    description = (embed.description or "").strip()
    if description and not _is_role_batch(embed):
        if not re.fullmatch(r"<?@!?\d{15,22}>?|@[^\n]{1,80}", description):
            return description[:700]
    return "SentriX a enregistré cet événement et regroupé les informations disponibles dans une fiche d'audit unique."


def _avatar(bot: commands.Bot, guild: discord.Guild, embed: discord.Embed) -> str | None:
    thumb = getattr(embed.thumbnail, "url", None)
    if thumb:
        return str(thumb)
    for token in ("auteur", "membre", "utilisateur", "cible", "effectue par", "moderateur", "acteur"):
        uid = _first_id(_field_value(embed, token))
        if not uid:
            continue
        user = guild.get_member(uid) or bot.get_user(uid)
        if user is not None:
            try:
                return str(user.display_avatar.url)
            except Exception:
                pass
    if guild.icon:
        return str(guild.icon.url)
    if bot.user:
        return str(bot.user.display_avatar.url)
    return None


def _resolved_channel(guild: discord.Guild, embed: discord.Embed):
    return v27._channel_from_value(guild, _field_value(embed, "salon", "channel"))


def _context_block(guild: discord.Guild, embed: discord.Embed) -> str:
    channel = _resolved_channel(guild, embed)
    salon_raw = _field_value(embed, "salon", "channel")
    salon = channel.mention if channel is not None else _one_line(salon_raw, 180)
    author = _field_value(embed, "auteur", "membre", "utilisateur", "cible")

    items: list[str] = []
    if salon_raw or channel is not None:
        items.append(f"💬 **Salon**  {salon}")
    if author:
        items.append(f"👤 **Auteur / cible**  {_real_user_mention(author, with_id=True)}")
    if not items:
        items.append(f"🖥️ **Serveur**  {discord.utils.escape_markdown(guild.name)}")
    return "### Contexte\n" + "   •   ".join(items)


def _action_block(embed: discord.Embed) -> str | None:
    actor = _field_value(embed, "effectue par", "moderateur", "acteur", "executant")
    reason = _field_value(embed, "raison", "raison audit log")
    duration = _field_value(embed, "duree", "fin du timeout", "nouvel etat")
    parts: list[str] = []
    if actor:
        actor_id = _first_id(actor)
        actor_display = f"<@{actor_id}> · `{actor_id}`" if actor_id else _one_line(actor, 260)
        if "bot" in _plain(actor):
            actor_display += " · 🤖 Bot"
        parts.append(f"🛡️ **Effectué par**  {actor_display}")
    if reason:
        parts.append(f"📝 **Raison**  {_one_line(reason, 300)}")
    if duration:
        parts.append(f"⏱️ **État / durée**  {_one_line(duration, 260)}")
    if not parts:
        return None
    return "### Action\n" + "   •   ".join(parts)


def _data_block(embed: discord.Embed) -> str | None:
    if _is_role_batch(embed):
        description = (embed.description or "").strip()
        return f"### Détails groupés\n{description[:3000]}" if description else None

    content = _field_value(embed, "contenu")
    before = _field_value(embed, "avant")
    after = _field_value(embed, "apres")
    attachments = _field_value(embed, "pieces jointes", "pièces jointes")
    access = _field_value(embed, "acces", "accès")

    lines: list[str] = []
    if content:
        lines.append(f"**Contenu**\n> {str(content)[:1100].replace(chr(10), chr(10) + '> ')}")
    if before or after:
        if before:
            lines.append(f"**◀ Avant**\n{str(before)[:850]}")
        if after:
            lines.append(f"**▶ Après**\n{str(after)[:850]}")
    if attachments:
        lines.append(f"**Pièces jointes**\n{str(attachments)[:900]}")
    if access:
        lines.append(f"**Accès**\n{str(access)[:500]}")
    if not lines:
        return None
    return "### Données\n" + "\n\n".join(lines)


def _extra_blocks(embed: discord.Embed) -> list[str]:
    extras: list[str] = []
    for field in embed.fields:
        name = _plain(str(field.name))
        if any(marker in name for marker in KNOWN_FIELD_MARKERS):
            continue
        value = str(field.value).strip() or "Non disponible"
        extras.append(f"**{str(field.name)[:120]}**\n{value[:900]}")
    if not extras:
        return []

    blocks: list[str] = []
    current = "### Informations complémentaires"
    for item in extras:
        candidate = current + "\n\n" + item
        if len(candidate) > 3300:
            blocks.append(current)
            current = "### Informations complémentaires\n\n" + item
        else:
            current = candidate
    blocks.append(current)
    return blocks[:3]


def _trace_block(guild: discord.Guild, log_type: str, embed: discord.Embed) -> str:
    event = _event(log_type, embed)
    message_id = _message_id(log_type, embed)
    channel = _resolved_channel(guild, embed)
    actor_id = _first_id(_field_value(embed, "effectue par", "moderateur", "acteur"))
    target_id = _target_id(embed)
    ts = _event_timestamp(embed)

    parts: list[str] = []
    if message_id:
        parts.append(f"🆔 **ID du message** `{message_id}`")
    elif target_id:
        label = "ID cible"
        if event.startswith("role_"):
            label = "ID du rôle"
        elif event.startswith("channel_"):
            label = "ID du salon"
        parts.append(f"🆔 **{label}** `{target_id}`")
    if channel is not None:
        parts.append(f"#️⃣ **ID salon** `{channel.id}`")
    if actor_id:
        parts.append(f"🛡️ **ID acteur** `{actor_id}`")
    parts.append(f"🖥️ **ID serveur** `{guild.id}`")

    return (
        "### Traçabilité\n"
        + "   •   ".join(parts[:4])
        + f"\n-# Horodatage : <t:{ts}:F> • <t:{ts}:R> • Journal sécurisé SentriX"
    )


def _buttons(guild: discord.Guild, log_type: str, embed: discord.Embed, inherited: list[tuple[str, int]]) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    message_id = _message_id(log_type, embed)
    channel = _resolved_channel(guild, embed)
    author_id = _first_id(_field_value(embed, "auteur", "membre", "utilisateur", "cible"))
    actor_id = _first_id(_field_value(embed, "effectue par", "moderateur", "acteur"))

    if message_id:
        result.append(("Copier ID message", message_id))
    if channel is not None:
        result.append(("Copier ID salon", channel.id))
    if author_id:
        result.append(("Copier ID auteur", author_id))
    if actor_id and actor_id != author_id:
        result.append(("Copier ID modérateur", actor_id))

    for label, value in inherited:
        try:
            pair = (str(label), int(value))
        except (TypeError, ValueError):
            continue
        if any(existing_value == pair[1] for _, existing_value in result):
            continue
        result.append(pair)
    return result[:5]


def _fingerprint(guild: discord.Guild, log_type: str, embed: discord.Embed) -> str:
    message_id = _message_id(log_type, embed)
    event = _event(log_type, embed)
    if message_id:
        return f"{guild.id}:{event}:message:{message_id}"
    target = _target_id(embed)
    if target:
        return f"{guild.id}:{event}:{target}"
    raw = "|".join(
        [str(embed.title or ""), str(embed.description or "")]
        + [f"{field.name}:{field.value}" for field in embed.fields]
    )
    digest = hashlib.sha1(_plain(raw).encode("utf-8", "ignore")).hexdigest()[:18]
    return f"{guild.id}:{event}:{digest}"


class PremiumAuditLogV28(discord.ui.LayoutView):
    """Fiche d'audit large : même architecture pour toutes les catégories de logs."""

    _sentrix_log_layout = True
    _sentrix_rectangle_v25 = True
    _sentrix_reference_v26 = True
    _sentrix_unified_v27 = True
    _sentrix_premium_v28 = True

    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        buttons: list[tuple[str, int]],
    ):
        super().__init__(timeout=6 * 60 * 60)
        clean = _silent_mention_embed(embed)
        v27._restore_channel_mentions(guild, clean)
        clean = _ensure_message_id_field(log_type, clean)

        accent = int(clean.colour.value) if clean.colour else 0x7C5CFC
        category, category_emoji = _category(log_type)
        event_ts = _event_timestamp(clean)
        container = discord.ui.Container(accent_colour=accent)

        header_text = (
            f"-# ◆ SENTRIX AUDIT • {category_emoji} {category} • {guild.name}\n\n"
            f"# {_title(log_type, clean)}\n"
            f"**● ÉVÉNEMENT ENREGISTRÉ**  ·  <t:{event_ts}:R>\n\n"
            f"{_summary(log_type, clean)}"
        )[:3900]
        header = discord.ui.TextDisplay(header_text)
        avatar = _avatar(bot, guild, clean)
        if avatar:
            try:
                container.add_item(
                    discord.ui.Section(
                        header,
                        accessory=discord.ui.Thumbnail(
                            avatar,
                            description="Identité principale liée à l'événement",
                        ),
                    )
                )
            except Exception:
                container.add_item(header)
        else:
            container.add_item(header)

        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(_context_block(guild, clean)[:3900]))

        action = _action_block(clean)
        if action:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(action[:3900]))

        data = _data_block(clean)
        if data:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(data[:3900]))

        for block in _extra_blocks(clean):
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(block[:3900]))

        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(_trace_block(guild, log_type, clean)[:3900]))

        final_buttons = _buttons(guild, log_type, clean, buttons)
        if final_buttons:
            row = discord.ui.ActionRow()
            for index, (label, value) in enumerate(final_buttons):
                row.add_item(premium_logs_v2.CopyIdButton(label, int(value), index))
            if row.children:
                container.add_item(row)

        self._sentrix_log_fingerprint = _fingerprint(guild, log_type, clean)
        self._sentrix_is_log_layout = True
        self.add_item(container)


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del bot, extension_name
    global _RENDER_INSTALLED
    required = ("LayoutView", "Container", "Section", "TextDisplay", "Thumbnail", "Separator")
    if not all(hasattr(discord.ui, name) for name in required):
        return
    premium_logs_v2.PremiumLogLayout = PremiumAuditLogV28
    _RENDER_INSTALLED = True


__all__ = ["install", "install_source_guard", "PremiumAuditLogV28"]
