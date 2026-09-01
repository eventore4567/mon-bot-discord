"""SentriX V27 — pipeline unique des logs Discord.

Objectifs :
- dédupliquer un même événement AVANT les anciens renderers, même si deux listeners lui
  donnent des titres différents (ex. ``SentriX • Journal`` et ``Message supprimé``) ;
- conserver un seul rendu final Components V2, grand et horizontal même pour un contenu
  court ;
- conserver les salons sous forme de vraie mention <#id> cliquable ;
- transformer les mentions membres/rôles en texte pour ne jamais ping ;
- enrichir les actions externes via l'Audit Log, y compris lorsqu'elles viennent d'un
  autre bot ;
- laisser le batch rôles existant regrouper >=3 rôles dans sa fenêtre fixe de 3 secondes.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from datetime import timedelta

import discord
from discord.ext import commands

from utils import log_service
from . import premium_logs_v2
from .premium_logs import _button_items
from .log_rectangle_v25 import (
    CATEGORY_LABELS,
    _event_timestamp,
    _field_value,
    _is_role_batch,
    _sanitized_embed,
    _target_id,
)

logger = logging.getLogger("bot.log-single-pipeline-v27")
_INSTALLED = False
_SOURCE_TTL = 8.0
_SOURCE_RECENT: dict[str, float] = {}

AUDIT_ACTIONS: dict[str, discord.AuditLogAction] = {
    "message_delete": discord.AuditLogAction.message_delete,
    "member_ban": discord.AuditLogAction.ban,
    "member_unban": discord.AuditLogAction.unban,
    "member_timeout": discord.AuditLogAction.member_update,
    "member_role_update": discord.AuditLogAction.member_role_update,
    "channel_create": discord.AuditLogAction.channel_create,
    "channel_delete": discord.AuditLogAction.channel_delete,
    "channel_update": discord.AuditLogAction.channel_update,
    "role_create": discord.AuditLogAction.role_create,
    "role_delete": discord.AuditLogAction.role_delete,
    "role_update": discord.AuditLogAction.role_update,
    "guild_update": discord.AuditLogAction.guild_update,
}

TITLES = {
    "message_delete": "Message supprimé",
    "message_edit": "Message modifié",
    "member_ban": "Membre banni",
    "member_unban": "Membre débanni",
    "member_timeout": "Timeout modifié",
    "member_role_update": "Rôles d'un membre modifiés",
    "channel_create": "Salon créé",
    "channel_delete": "Salon supprimé",
    "channel_update": "Salon modifié",
    "role_create": "Rôle créé",
    "role_delete": "Rôle supprimé",
    "role_update": "Rôle modifié",
    "guild_update": "Serveur modifié",
}

EMOJIS = {
    "message_delete": "🗑️",
    "message_edit": "✏️",
    "member_ban": "🔨",
    "member_unban": "🔓",
    "member_timeout": "⏱️",
    "member_role_update": "🏷️",
    "channel_create": "💬",
    "channel_delete": "💬",
    "channel_update": "⚙️",
    "role_create": "🏷️",
    "role_delete": "🏷️",
    "role_update": "🏷️",
    "guild_update": "⚙️",
}


def _plain(value: str | None) -> str:
    value = str(value or "").casefold()
    replacements = (
        ("é", "e"), ("è", "e"), ("ê", "e"), ("ë", "e"),
        ("à", "a"), ("â", "a"), ("ä", "a"),
        ("ù", "u"), ("û", "u"), ("ü", "u"),
        ("ô", "o"), ("ö", "o"), ("î", "i"), ("ï", "i"),
        ("ç", "c"),
    )
    for old, new in replacements:
        value = value.replace(old, new)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value)).strip()


def _first_id(value: str | None) -> int | None:
    match = re.search(r"(?<!\d)(\d{15,22})(?!\d)", str(value or ""))
    return int(match.group(1)) if match else None


def _field_names(embed: discord.Embed) -> set[str]:
    return {_plain(str(field.name)) for field in embed.fields}


def _event_kind(log_type: str, embed: discord.Embed) -> str:
    title = _plain(str(embed.title or ""))
    description = _plain(str(embed.description or ""))
    names = _field_names(embed)
    sample = f"{title} {description} {' '.join(sorted(names))}"

    if log_type == "messages":
        if "message modifie" in sample or "avant" in names or "apres" in names:
            return "message_edit"
        # Plusieurs anciennes couches renommeraient le titre en "SentriX • Journal".
        # Auteur + Salon + Contenu correspond néanmoins sans ambiguïté au delete logger.
        if "message supprime" in sample or {"auteur", "salon", "contenu"}.issubset(names):
            return "message_delete"

    checks = (
        ("member_ban", ("membre banni", "bannissement")),
        ("member_unban", ("membre debanni", "debannissement")),
        ("member_timeout", ("timeout",)),
        ("member_role_update", ("roles d un membre", "role attribue", "role retire")),
        ("channel_create", ("salon cree",)),
        ("channel_delete", ("salon supprime",)),
        ("channel_update", ("salon modifie",)),
        ("role_create", ("role cree",)),
        ("role_delete", ("role supprime",)),
        ("role_update", ("role modifie",)),
        ("guild_update", ("serveur modifie",)),
    )
    for key, markers in checks:
        if any(marker in sample for marker in markers):
            return key
    return f"{log_type}:{title[:80] or 'event'}"


def _channel_from_value(guild: discord.Guild, value: str | None) -> discord.abc.GuildChannel | None:
    raw = str(value or "")
    match = re.search(r"<#(\d{15,22})>", raw)
    if not match:
        match = re.search(r"(?<!\d)(\d{15,22})(?!\d)", raw)
    if match:
        channel = guild.get_channel(int(match.group(1)))
        if channel is not None:
            return channel

    # Anciennes couches peuvent avoir transformé <#id> en simple #nom. On restaure alors
    # la vraie mention grâce au cache guild.channels.
    plain_raw = _plain(raw)
    candidates = sorted(guild.channels, key=lambda item: len(item.name), reverse=True)
    for channel in candidates:
        if _plain(channel.name) and _plain(channel.name) in plain_raw:
            return channel
    return None


def _restore_channel_mentions(guild: discord.Guild, embed: discord.Embed) -> None:
    for index, field in enumerate(list(embed.fields)):
        if "salon" not in _plain(str(field.name)) and "channel" not in _plain(str(field.name)):
            continue
        channel = _channel_from_value(guild, str(field.value))
        if channel is None:
            continue
        embed.set_field_at(
            index,
            name=str(field.name),
            value=f"{channel.mention}\n`ID : {channel.id}`",
            inline=False,
        )


def _canonicalize(guild: discord.Guild, log_type: str, source: discord.Embed) -> tuple[discord.Embed, str]:
    embed = source.copy()
    event = _event_kind(log_type, embed)
    canonical_title = TITLES.get(event)
    if canonical_title:
        embed.title = canonical_title
    _restore_channel_mentions(guild, embed)
    return embed, event


def _semantic_key(guild: discord.Guild, log_type: str, embed: discord.Embed, event: str) -> str:
    if event in {"message_delete", "message_edit"}:
        author = _field_value(embed, "auteur")
        salon = _field_value(embed, "salon")
        content = _field_value(embed, "contenu", "avant", "apres")
        author_id = _first_id(author)
        channel = _channel_from_value(guild, salon)
        author_key = str(author_id or _plain(author)[:80])
        channel_key = str(getattr(channel, "id", None) or _first_id(salon) or _plain(salon)[:100])
        digest = hashlib.sha1(_plain(content).encode("utf-8", "ignore")).hexdigest()[:14]
        # Une fenêtre courte permet de reconnaître deux anciens listeners sans fusionner
        # durablement des événements légitimes ultérieurs.
        bucket = int(time.time() // 4)
        return f"{guild.id}:{event}:{author_key}:{channel_key}:{digest}:{bucket}"

    target = _target_id(embed)
    if target is None:
        for token in ("membre", "utilisateur", "cible", "role", "salon"):
            target = _first_id(_field_value(embed, token))
            if target:
                break
    if target:
        return f"{guild.id}:{event}:{target}"

    body = "|".join(
        [str(embed.title or ""), str(embed.description or "")]
        + [f"{field.name}:{field.value}" for field in embed.fields]
    )
    digest = hashlib.sha1(_plain(body).encode("utf-8", "ignore")).hexdigest()[:18]
    return f"{guild.id}:{event}:{digest}"


def _remember_source(key: str) -> bool:
    now = time.monotonic()
    for item, expiry in list(_SOURCE_RECENT.items())[:2000]:
        if expiry <= now:
            _SOURCE_RECENT.pop(item, None)
    if _SOURCE_RECENT.get(key, 0.0) > now:
        return False
    _SOURCE_RECENT[key] = now + _SOURCE_TTL
    return True


def _has_actor(embed: discord.Embed) -> bool:
    for field in embed.fields:
        name = _plain(str(field.name))
        if any(token in name for token in ("effectue par", "moderateur", "acteur", "executant")):
            return True
    return False


def _audit_target(embed: discord.Embed, event: str) -> int | None:
    if event == "message_delete":
        return _first_id(_field_value(embed, "auteur"))
    target = _target_id(embed)
    if target:
        return target
    for token in ("membre", "utilisateur", "cible", "role", "salon"):
        value = _first_id(_field_value(embed, token))
        if value:
            return value
    return None


def _actor_value(actor: discord.abc.User) -> str:
    display = getattr(actor, "display_name", None) or getattr(actor, "name", None) or str(actor)
    kind = "🤖 Bot" if getattr(actor, "bot", False) else "👤 Membre/Staff"
    return f"@{discord.utils.escape_markdown(str(display).replace('@', '＠'))}\n`{actor.id}` • {kind}"


async def _enrich_audit(guild: discord.Guild, embed: discord.Embed, event: str) -> None:
    action = AUDIT_ACTIONS.get(event)
    me = guild.me
    if action is None or _has_actor(embed) or me is None or not me.guild_permissions.view_audit_log:
        return

    target_id = _audit_target(embed, event)
    channel = _channel_from_value(guild, _field_value(embed, "salon")) if event == "message_delete" else None
    after = discord.utils.utcnow() - timedelta(seconds=15)

    # L'entrée d'audit peut arriver quelques centaines de ms après l'événement Gateway.
    if event in {"message_delete", "role_create", "role_delete", "role_update", "channel_create", "channel_delete", "channel_update", "member_ban", "member_unban"}:
        await asyncio.sleep(0.32)

    try:
        async for entry in guild.audit_logs(limit=12, action=action, after=after):
            entry_target = getattr(getattr(entry, "target", None), "id", None)
            if target_id is not None and entry_target not in {None, target_id}:
                continue
            if channel is not None:
                audit_channel = getattr(getattr(getattr(entry, "extra", None), "channel", None), "id", None)
                if audit_channel is not None and audit_channel != channel.id:
                    continue
            actor = entry.user
            if actor is None:
                continue
            embed.add_field(name="Effectué par", value=_actor_value(actor), inline=False)
            if entry.reason and not _field_value(embed, "raison"):
                embed.add_field(name="Raison Audit Log", value=str(entry.reason)[:1024], inline=False)
            return
    except (discord.Forbidden, discord.HTTPException):
        return
    except Exception:
        logger.exception("V27 : lecture Audit Log impossible guild=%s event=%s", guild.id, event)


def _avatar_url(bot: commands.Bot, guild: discord.Guild, embed: discord.Embed) -> str | None:
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


def _title(event: str, embed: discord.Embed) -> str:
    raw = str(embed.title or TITLES.get(event) or "Journal SentriX")
    emoji = EMOJIS.get(event, "📋")
    return raw if raw.startswith(emoji) else f"{emoji} {raw}"


def _description(event: str, embed: discord.Embed) -> str:
    current = (embed.description or "").strip()
    if current and not _is_role_batch(embed):
        return current[:950]
    if event == "message_delete":
        content = _field_value(embed, "contenu")
        if not content or content.strip() in {".", "..", "...", "[contenu inconnu]"}:
            return "SentriX a enregistré la suppression de ce message et conservé les informations disponibles dans le journal."
        return "SentriX a enregistré la suppression de ce message. Le contenu et le contexte disponibles sont affichés ci-dessous."
    if event == "message_edit":
        return "SentriX a enregistré la modification de ce message et conservé les valeurs disponibles avant et après l'édition."
    return "SentriX a enregistré cette action sur le serveur. Les informations utiles et l'auteur de l'action sont affichés ci-dessous."


def _detail_text(guild: discord.Guild, embed: discord.Embed) -> str:
    if _is_role_batch(embed):
        return (embed.description or "Aucun détail disponible.")[:3400]

    salon_raw = _field_value(embed, "salon")
    channel = _channel_from_value(guild, salon_raw)
    salon = channel.mention if channel is not None else salon_raw
    author = _field_value(embed, "auteur", "membre", "utilisateur", "cible")
    actor = _field_value(embed, "effectue par", "moderateur", "acteur")
    content = _field_value(embed, "contenu")
    before = _field_value(embed, "avant")
    after = _field_value(embed, "apres")
    reason = _field_value(embed, "raison")
    duration = _field_value(embed, "duree", "fin du timeout", "nouvel etat")

    lines: list[str] = []
    if salon:
        lines.append(f"### 💬 Salon\n{salon[:500]}")

    identities: list[str] = []
    if author:
        identities.append(f"**👤 Auteur / cible**\n{author[:550]}")
    if actor:
        identities.append(f"**🛡️ Effectué par**\n{actor[:550]}")
    if identities:
        lines.append("\n\n".join(identities))

    if content:
        lines.append(f"### 📝 Contenu\n{content[:900]}")
    elif before or after:
        values: list[str] = []
        if before:
            values.append(f"**◀️ Avant**\n{before[:650]}")
        if after:
            values.append(f"**▶️ Après**\n{after[:650]}")
        lines.append("\n\n".join(values))

    extras: list[str] = []
    if reason:
        extras.append(f"**📝 Raison** {reason[:600]}")
    if duration:
        extras.append(f"**⏱️ Durée / fin** {duration[:450]}")
    if extras:
        lines.append("\n".join(extras))

    return "\n\n".join(lines[:4])[:3000]


class UnifiedLargeLogLayout(discord.ui.LayoutView):
    """Une seule carte, grande et horizontale, même si le contenu métier est très court."""

    _sentrix_log_layout = True
    _sentrix_rectangle_v25 = True
    _sentrix_reference_v26 = True
    _sentrix_unified_v27 = True

    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        buttons: list[tuple[str, int]],
    ):
        super().__init__(timeout=6 * 60 * 60)
        clean = _sanitized_embed(bot, guild, embed)
        _restore_channel_mentions(guild, clean)
        event = _event_kind(log_type, clean)
        accent = int(clean.colour.value) if clean.colour else 0x7C5CFC
        category = CATEGORY_LABELS.get(log_type, str(log_type).upper())

        container = discord.ui.Container(accent_colour=accent)
        header_text = (
            f"-# 🛡️ SENTRIX • {category} • {guild.name}\n\n"
            f"# {_title(event, clean)}\n\n"
            f"{_description(event, clean)}"
        )[:3900]
        header = discord.ui.TextDisplay(header_text)
        avatar = _avatar_url(bot, guild, clean)
        if avatar:
            try:
                container.add_item(
                    discord.ui.Section(
                        header,
                        accessory=discord.ui.Thumbnail(avatar, description="Identité liée à l'événement"),
                    )
                )
            except Exception:
                container.add_item(header)
        else:
            container.add_item(header)

        details = _detail_text(guild, clean)
        if details:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(details))

        container.add_item(discord.ui.Separator())
        target = _target_id(clean)
        footer = f"-# SentriX • Journal sécurisé • <t:{_event_timestamp(clean)}:R>"
        if target:
            footer += f" • ID `{target}`"
        container.add_item(discord.ui.TextDisplay(footer))

        final_buttons = _button_items(clean, str(clean.title or "")) or buttons
        if final_buttons:
            row = discord.ui.ActionRow()
            seen: set[tuple[str, int]] = set()
            for index, (label, value) in enumerate(final_buttons[:2]):
                key = (str(label), int(value))
                if key in seen:
                    continue
                seen.add(key)
                row.add_item(premium_logs_v2.CopyIdButton(str(label), int(value), index))
            if row.children:
                container.add_item(row)

        self._sentrix_log_fingerprint = _semantic_key(guild, log_type, clean, event)
        self._sentrix_is_log_layout = True
        self.add_item(container)


def _install_source_guard(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    previous = log_service.send_log
    if getattr(previous, "_sentrix_single_pipeline_v27", False):
        _INSTALLED = True
        return

    async def send_log_once(
        inner_bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        file: discord.File | None = None,
    
        **identity,
    ) -> bool:
        canonical, event = _canonicalize(guild, str(log_type), embed, **identity)
        key = _semantic_key(guild, str(log_type), canonical, event)
        if not _remember_source(key):
            logger.debug("V27 : doublon source bloqué guild=%s event=%s", guild.id, event)
            return True

        # Les pièces jointes/transcripts ne doivent jamais attendre l'Audit Log.
        if file is None:
            await _enrich_audit(guild, canonical, event)

        return await previous(inner_bot, guild, log_type, canonical, file=file)

    send_log_once._sentrix_single_pipeline_v27 = True
    send_log_once._sentrix_original = previous
    log_service.send_log = send_log_once
    _INSTALLED = True
    logger.info("V27 : déduplication source + audit acteurs externes activés.")


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del extension_name
    required = ("LayoutView", "Container", "Section", "TextDisplay", "Thumbnail", "Separator")
    if not all(hasattr(discord.ui, name) for name in required):
        logger.warning("V27 : Components V2 incomplets, conservation du renderer précédent.")
        return

    _install_source_guard(bot)
    # Toujours le dernier renderer, même si V25/V26 ont été rappelés juste avant.
    premium_logs_v2.PremiumLogLayout = UnifiedLargeLogLayout


__all__ = ["install", "UnifiedLargeLogLayout"]
