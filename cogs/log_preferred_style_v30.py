"""SentriX V30 — rendu final compact, large et lisible pour tous les journaux.

V27/V28 conservent le routage, la déduplication, les IDs et les mentions silencieuses.
V30 garde une seule carte Components V2 par événement, mais laisse davantage de place
aux informations utiles des membres/rôles tout en restant horizontale et sans doublon.
Les vraies mentions Discord restent cliquables ; le garde V25 applique
AllowedMentions.none() au dernier envoi, donc aucun membre/rôle n'est réellement ping.
"""
from __future__ import annotations

import hashlib
import re

import discord
from discord.ext import commands

from . import premium_logs_v2
from . import log_premium_v28 as v28
from .log_rectangle_v25 import _event_timestamp, _field_value, _is_role_batch, _target_id


CATEGORY_ICON = {
    "messages": "💬",
    "tickets": "🎫",
    "moderation": "🛡️",
    "voice": "🔊",
    "server": "⚙️",
    "members": "👥",
    "roles": "🏷️",
    "security": "🛡️",
    "automod": "🛡️",
    "economy": "💳",
    "levels": "📈",
    "ai": "✨",
    "games": "🎮",
    "system": "🖥️",
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
    "member_role_update": "🏷️",
    "channel_create": "➕",
    "channel_delete": "➖",
    "channel_update": "⚙️",
    "role_create": "➕",
    "role_delete": "➖",
    "role_update": "⚙️",
    "guild_update": "⚙️",
}

CONTEXT_NAMES = {
    "salon", "channel", "auteur", "membre", "utilisateur", "cible",
    "effectue par", "effectué par", "moderateur", "modérateur",
    "acteur", "executant", "exécutant",
}
ID_NAMES = {
    "id", "id message", "id du message", "identifiant du message", "id salon",
    "id serveur", "id auteur", "id membre", "id cible", "identifiant",
}


def _event(log_type: str, embed: discord.Embed) -> str:
    return v28._event(log_type, embed)


def _norm(value: str | None) -> str:
    text = str(value or "").casefold()
    for old, new in (
        ("é", "e"), ("è", "e"), ("ê", "e"), ("ë", "e"), ("à", "a"),
        ("ù", "u"), ("ô", "o"), ("î", "i"), ("ç", "c"),
    ):
        text = text.replace(old, new)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _one_line(value: object, limit: int = 220) -> str:
    text = re.sub(r"\s*\n\s*", " · ", str(value or "").strip())
    text = re.sub(r"\s{2,}", " ", text)
    if not text:
        return "Non disponible"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _restore_role_mentions(guild: discord.Guild, value: object) -> str:
    """Restaure @NomDuRôle en vraie mention <@&id> sans permettre le ping.

    Les nouvelles sources utilisent déjà role.mention. Cette restauration couvre aussi les
    anciennes couches qui avaient transformé une mention en simple texte @NomDuRôle.
    AllowedMentions.none() est imposé plus bas dans le pipeline V25.
    """
    text = str(value or "")
    if not text:
        return text
    text = text.replace("@everyone", "＠everyone").replace("@here", "＠here")
    roles = sorted(
        (role for role in guild.roles if not role.is_default()),
        key=lambda role: len(role.name),
        reverse=True,
    )
    for role in roles:
        marker = f"@{role.name}"
        if marker in text:
            text = text.replace(marker, role.mention)
    return text


def _is_id_field(name: str) -> bool:
    normalized = _norm(name)
    normalized_ids = {_norm(item) for item in ID_NAMES}
    return (
        normalized in normalized_ids
        or normalized.startswith("id ")
        or normalized.startswith("identifiant ")
    )


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
        "members": 0x5865F2,
        "roles": 0x9B59B6,
        "channels": 0x5865F2,
        "cases": 0xED4245,
        "spam": 0xFEE75C,
        "raid": 0xED4245,
        "staff": 0x5865F2,
    }.get(str(log_type), 0x7C5CFC)


def _title(log_type: str, embed: discord.Embed) -> str:
    raw = re.sub(r"\s+", " ", str(embed.title or "Journal SentriX")).strip()
    raw = re.sub(r"^[^\wÀ-ÿ]+\s*", "", raw).strip() or "Journal SentriX"
    plain = _norm(raw)
    if "membre arrive" in plain:
        icon = "📥"
    elif "membre parti" in plain:
        icon = "📤"
    else:
        icon = EVENT_ICON.get(_event(log_type, embed)) or CATEGORY_ICON.get(str(log_type), "📋")
    return f"{icon} {raw}"


def _mention_or_text(value: str | None, limit: int = 150) -> str:
    uid = v28._first_id(value)
    if uid:
        return f"<@{uid}>"
    return _one_line(value, limit)


def _context_line(guild: discord.Guild, log_type: str, embed: discord.Embed) -> tuple[str, set[int]]:
    consumed: set[int] = set()
    for index, field in enumerate(embed.fields):
        name = _norm(str(field.name))
        if any(token == name or token in name for token in CONTEXT_NAMES):
            consumed.add(index)

    chunks: list[str] = []
    channel = v28._resolved_channel(guild, embed)
    channel_raw = _field_value(embed, "salon", "channel")
    target = _field_value(embed, "auteur", "membre", "utilisateur", "cible")
    actor = _field_value(
        embed,
        "effectue par", "effectué par", "moderateur", "modérateur",
        "acteur", "executant", "exécutant",
    )

    # Les logs d'arrivée/départ avaient parfois seulement l'ID dans le footer. On le
    # transforme maintenant en vraie mention membre pour garder la même qualité visuelle
    # que les logs de messages.
    if not target and str(log_type) in {"members", "moderation"}:
        footer_target = _target_id(embed)
        if footer_target:
            target = f"<@{footer_target}>"

    if target:
        chunks.append(f"👤 **Cible** {_mention_or_text(target)}")
    if channel is not None:
        chunks.append(f"💬 **Salon** {channel.mention}")
    elif channel_raw:
        chunks.append(f"💬 **Salon** {_one_line(channel_raw, 160)}")
    if actor:
        chunks.append(f"🛡️ **Par** {_mention_or_text(actor)}")
    if not chunks:
        chunks.append(f"🖥️ **Serveur** {discord.utils.escape_markdown(guild.name)}")
    return "  •  ".join(chunks[:3]), consumed


def _generic_details(guild: discord.Guild, embed: discord.Embed, consumed: set[int]) -> str | None:
    """Affiche plus d'informations tout en gardant une seule carte horizontale."""
    if _is_role_batch(embed):
        description = (embed.description or "").strip()
        description = _restore_role_mentions(guild, description)
        return _one_line(description, 760) if description else None

    items: list[str] = []
    before = _field_value(embed, "avant")
    after = _field_value(embed, "apres")
    if before:
        items.append(f"**Avant** {_one_line(_restore_role_mentions(guild, before), 220)}")
    if after:
        items.append(f"**Après** {_one_line(_restore_role_mentions(guild, after), 220)}")

    for index, field in enumerate(embed.fields):
        if index in consumed:
            continue
        name = str(field.name).strip() or "Info"
        normalized = _norm(name)
        if _is_id_field(name) or normalized in {"avant", "apres"}:
            continue
        value = str(field.value or "").strip()
        if not value:
            continue
        value = _restore_role_mentions(guild, value)
        clean_name = re.sub(r"^[^\wÀ-ÿ]+\s*", "", name).strip() or "Info"
        if any(token in normalized for token in ("contenu", "raison", "commande", "roles", "rôles")):
            per_item = 360
        else:
            per_item = 230
        items.append(f"**{clean_name}** {_one_line(value, per_item)}")
        if len(items) >= 6:
            break

    if not items:
        description = (embed.description or "").strip()
        description = _restore_role_mentions(guild, description)
        return _one_line(description, 620) if description else None
    return "  •  ".join(items)[:1500]


def _ids_line(guild: discord.Guild, log_type: str, embed: discord.Embed) -> str:
    ids: list[str] = []
    message_id = v28._message_id(log_type, embed)
    target = v28._first_id(_field_value(embed, "auteur", "membre", "utilisateur", "cible"))
    if target is None and str(log_type) in {"members", "moderation"}:
        target = _target_id(embed)
    channel = v28._resolved_channel(guild, embed)
    if message_id:
        ids.append(f"msg `{message_id}`")
    if target and target != message_id:
        ids.append(f"cible `{target}`")
    if channel is not None:
        ids.append(f"salon `{channel.id}`")
    ids.append(f"serveur `{guild.id}`")
    return " • ".join(ids[:4])


def _canonical_fingerprint(guild: discord.Guild, log_type: str, embed: discord.Embed) -> str:
    """Empreinte finale stable pour que deux renderers/listeners ne publient pas deux cartes."""
    event = _event(log_type, embed)
    message_id = v28._message_id(log_type, embed)
    if message_id:
        return f"{guild.id}:{event}:message:{message_id}"

    target = v28._first_id(_field_value(embed, "auteur", "membre", "utilisateur", "cible"))
    if target is None:
        target = v28._first_id(getattr(getattr(embed, "footer", None), "text", None))
    channel = v28._resolved_channel(guild, embed)
    if target:
        return f"{guild.id}:{event}:target:{target}:channel:{getattr(channel, 'id', 0) or 0}"

    core = []
    for field in embed.fields:
        if _is_id_field(str(field.name)):
            continue
        core.append(f"{_norm(str(field.name))}:{_norm(_one_line(field.value, 240))}")
    raw = "|".join([event, _norm(embed.title), _norm(embed.description), *core[:6]])
    digest = hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:20]
    return f"{guild.id}:{event}:{digest}"


def _button_items(guild: discord.Guild, log_type: str, embed: discord.Embed) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    message_id = v28._message_id(log_type, embed)
    target = v28._first_id(_field_value(embed, "auteur", "membre", "utilisateur", "cible"))
    if target is None and str(log_type) in {"members", "moderation"}:
        target = _target_id(embed)
    channel = v28._resolved_channel(guild, embed)
    if message_id:
        result.append(("ID message", message_id))
    if target and target != message_id:
        result.append(("ID cible", target))
    if channel is not None:
        result.append(("ID salon", channel.id))
    return result[:3]


class PreferredLogV30(discord.ui.LayoutView):
    """Rendu final : une carte large avec davantage d'informations, sans empilement inutile."""

    _sentrix_log_layout = True
    _sentrix_rectangle_v25 = True
    _sentrix_reference_v26 = True
    _sentrix_unified_v27 = True
    _sentrix_premium_v28 = True
    _sentrix_ultra_v29 = True
    _sentrix_preferred_v30 = True

    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        buttons: list[tuple[str, int]],
    ):
        super().__init__(timeout=6 * 60 * 60)
        del buttons
        clean = v28._silent_mention_embed(embed)
        v28.v27._restore_channel_mentions(guild, clean)
        clean = v28._ensure_message_id_field(log_type, clean)

        category, _category_icon = v28._category(log_type)
        ts = _event_timestamp(clean)
        context, consumed = _context_line(guild, str(log_type), clean)
        details = _generic_details(guild, clean, consumed)

        lines = [
            f"-# 🛡️ SENTRIX • {category} • {guild.name} • <t:{ts}:R>",
            f"## {_title(log_type, clean)}",
            context,
        ]
        if details:
            lines.append(details)
        lines.append(f"-# {_ids_line(guild, log_type, clean)}")

        container = discord.ui.Container(accent_colour=_accent(log_type, clean))
        container.add_item(discord.ui.TextDisplay("\n".join(lines)[:2800]))

        final_buttons = _button_items(guild, log_type, clean)
        if final_buttons:
            row = discord.ui.ActionRow()
            seen: set[int] = set()
            for index, (label, value) in enumerate(final_buttons):
                value = int(value)
                if value in seen:
                    continue
                seen.add(value)
                row.add_item(premium_logs_v2.CopyIdButton(label, value, index))
            if row.children:
                container.add_item(row)

        self._sentrix_log_fingerprint = _canonical_fingerprint(guild, log_type, clean)
        self._sentrix_is_log_layout = True
        self.add_item(container)


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del bot, extension_name
    required = ("LayoutView", "Container", "TextDisplay")
    if not all(hasattr(discord.ui, name) for name in required):
        return
    premium_logs_v2.PremiumLogLayout = PreferredLogV30


__all__ = ["install", "PreferredLogV30"]