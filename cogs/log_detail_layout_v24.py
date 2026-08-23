"""SentriX V24 — journal premium unique, large, compact et silencieux.

Le rendu vise la carte de référence demandée : en-tête fin, grand titre d'événement,
description courte, avatar à droite, quelques sections utiles pleine largeur, footer
compact et boutons ID. Discord décide de la largeur pixel réelle ; le layout évite donc
les blocs verticaux inutiles pour rester large et peu haut.

Garanties :
- UNE seule carte par événement (service Railway primaire + déduplication TTL 8 s) ;
- aucune mention membre/rôle/salon n'est envoyée comme mention Discord ;
- AllowedMentions.none() est toujours appliqué aux cartes V24 ;
- les données métier déjà collectées (auteur, raison, durée, Audit Log, contenu...) restent ;
- les rafales de rôles préparées par logs_no_ping restent une liste unique.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
import unicodedata
from datetime import datetime, timezone

import discord
from discord.ext import commands

from utils import log_service
from . import premium_logs_v2
from .premium_logs import style_log, _button_items

logger = logging.getLogger("bot.log-detail-layout-v24")
_INSTALLED = False

# Service Railway qui doit réellement publier les journaux. L'ID est stable même si le
# nom du service change dans Railway.
DEFAULT_PRIMARY_LOG_SERVICE_ID = "d4fb0c3a-d62b-4817-aae1-3cfc859d32c0"
DEFAULT_PRIMARY_LOG_SERVICE = "mon-bot-discord"
DEDUPE_TTL_SECONDS = 8.0
_RECENT_LOGS: dict[str, float] = {}

CATEGORY_LABELS = {
    "messages": "MESSAGES",
    "members": "MEMBRES",
    "roles": "RÔLES",
    "server": "SERVEUR",
    "voice": "VOCAL",
    "moderation": "MODÉRATION",
    "automod": "SÉCURITÉ",
    "security": "SÉCURITÉ",
    "tickets": "TICKETS",
    "economy": "ÉCONOMIE",
    "levels": "NIVEAUX",
    "ai": "IA",
    "games": "JEUX",
    "system": "SYSTÈME",
}

EVENT_MARKERS = (
    "message supprime", "message modifie", "messages supprimes",
    "role cree", "role supprime", "role modifie", "creation de roles",
    "suppression de roles", "modification de roles",
    "membre banni", "bannissement", "membre debanni", "debannissement",
    "membre expulse", "kick", "timeout", "mute", "warn",
    "salon cree", "salon supprime", "salon modifie",
    "membre arrive", "membre parti", "vocal", "ticket",
)


def _plain(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9]+", " ", text)).casefold().strip()


def _first_id(value: str | None) -> int | None:
    match = re.search(r"(?<!\d)(\d{15,22})(?!\d)", value or "")
    return int(match.group(1)) if match else None


def _footer_target(embed: discord.Embed) -> int | None:
    return _first_id(getattr(getattr(embed, "footer", None), "text", None))


def _event_timestamp(embed: discord.Embed) -> int:
    stamp = embed.timestamp
    if stamp is None:
        stamp = datetime.now(timezone.utc)
    elif stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return int(stamp.timestamp())


def _service_name_matches(service: str, primary: str) -> bool:
    if service == primary:
        return True
    # Les statuts GitHub/Railway peuvent préfixer le service par le nom du projet.
    return service.endswith(" - " + primary)


def _is_primary_log_service() -> bool:
    service_id = (os.getenv("RAILWAY_SERVICE_ID") or "").strip()
    wanted_id = (
        os.getenv("SENTRIX_LOG_PRIMARY_SERVICE_ID")
        or DEFAULT_PRIMARY_LOG_SERVICE_ID
    ).strip()
    if service_id:
        return service_id == wanted_id

    service = (os.getenv("RAILWAY_SERVICE_NAME") or "").strip().casefold()
    if not service:
        # En local, ne pas désactiver les logs par accident.
        return True
    primary = (
        os.getenv("SENTRIX_LOG_PRIMARY_SERVICE")
        or os.getenv("SENTRIX_ALERT_PRIMARY_SERVICE")
        or DEFAULT_PRIMARY_LOG_SERVICE
    ).strip().casefold()
    return _service_name_matches(service, primary)


def _display_user(bot: commands.Bot, guild: discord.Guild, user_id: int) -> str:
    member = guild.get_member(user_id)
    user = member or bot.get_user(user_id)
    if user is None:
        return f"@Utilisateur-{user_id}"
    name = getattr(user, "display_name", None) or getattr(user, "name", None) or str(user)
    return "@" + discord.utils.escape_markdown(str(name).replace("`", "'"))


def _display_role(guild: discord.Guild, role_id: int) -> str:
    role = guild.get_role(role_id)
    if role is None:
        return f"@Rôle-{role_id}"
    return "@" + discord.utils.escape_markdown(role.name.replace("`", "'"))


def _display_channel(guild: discord.Guild, channel_id: int) -> str:
    channel = guild.get_channel(channel_id)
    if channel is None:
        return f"#salon-{channel_id}"
    return "#" + discord.utils.escape_markdown(channel.name.replace("`", "'"))


def _deping_text(bot: commands.Bot, guild: discord.Guild, value: str | None) -> str:
    """Transforme les syntaxes de mention Discord en texte pur avant rendu."""
    text = str(value or "")
    text = re.sub(
        r"<@!?(\d{15,22})>",
        lambda m: _display_user(bot, guild, int(m.group(1))),
        text,
    )
    text = re.sub(
        r"<@&(\d{15,22})>",
        lambda m: _display_role(guild, int(m.group(1))),
        text,
    )
    text = re.sub(
        r"<#(\d{15,22})>",
        lambda m: _display_channel(guild, int(m.group(1))),
        text,
    )
    return text


def _sanitize_embed(bot: commands.Bot, guild: discord.Guild, source: discord.Embed) -> discord.Embed:
    embed = source.copy()
    if embed.title:
        embed.title = _deping_text(bot, guild, embed.title)[:256]
    if embed.description:
        embed.description = _deping_text(bot, guild, embed.description)[:4096]
    for index, field in enumerate(list(embed.fields)):
        embed.set_field_at(
            index,
            name=_deping_text(bot, guild, str(field.name))[:256],
            value=_deping_text(bot, guild, str(field.value))[:1024],
            inline=field.inline,
        )
    return embed


def _field_exists(embed: discord.Embed, *labels: str) -> bool:
    wanted = {_plain(label) for label in labels}
    return any(_plain(str(field.name)) in wanted for field in embed.fields)


def _add_field(embed: discord.Embed, name: str, value: str) -> None:
    if len(embed.fields) >= 25 or _field_exists(embed, name):
        return
    embed.add_field(name=name[:256], value=(value or "Aucune information")[:1024], inline=False)


def _user_context(bot: commands.Bot, guild: discord.Guild, user_id: int) -> str:
    member = guild.get_member(user_id)
    user = member or bot.get_user(user_id)
    lines = [f"{_display_user(bot, guild, user_id)} • ID `{user_id}`"]
    if user is not None:
        created = getattr(user, "created_at", None)
        if created is not None:
            lines.append(f"Compte créé <t:{int(created.timestamp())}:R> • {'Bot' if getattr(user, 'bot', False) else 'Utilisateur'}")
    if member is not None:
        roles = [role for role in member.roles if not role.is_default()]
        top = "Aucun rôle" if member.top_role.is_default() else _display_role(guild, member.top_role.id)
        joined = f" • arrivé <t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else ""
        lines.append(f"Rôle principal {top} • {len(roles)} rôle(s){joined}")
    return "\n".join(lines[:3])


def _role_context(guild: discord.Guild, role_id: int, embed: discord.Embed) -> str:
    role = guild.get_role(role_id)
    if role is None:
        label = (embed.description or "Rôle supprimé").splitlines()[0].strip()[:100]
        return f"**{label}** • ID `{role_id}` • rôle supprimé/introuvable"
    enabled_permissions = sum(1 for _name, enabled in role.permissions if enabled)
    return (
        f"{_display_role(guild, role.id)} • ID `{role.id}` • position **{role.position}**\n"
        f"Couleur `{role.colour}` • {enabled_permissions} permission(s) • "
        f"séparé **{'oui' if role.hoist else 'non'}** • mentionnable **{'oui' if role.mentionable else 'non'}**"
    )


def _channel_context(guild: discord.Guild, channel_id: int, embed: discord.Embed) -> str:
    channel = guild.get_channel(channel_id)
    if channel is None:
        label = (embed.description or "Salon supprimé").splitlines()[0].strip()[:100]
        return f"**{label}** • ID `{channel_id}` • salon supprimé/inaccessible"
    category = getattr(channel, "category", None)
    category_text = category.name if category else "Aucune catégorie"
    return (
        f"`{_display_channel(guild, channel.id)}` • ID `{channel.id}` • {channel.type}\n"
        f"Catégorie **{category_text}** • position **{channel.position}**"
    )


def _looks_like_member_target(log_type: str, title: str) -> bool:
    text = _plain(title)
    return log_type in {"members", "voice", "moderation", "economy", "levels", "ai", "games"} or any(
        marker in text for marker in ("membre", "utilisateur", "timeout", "banni", "ban", "kick", "mute", "warn", "surnom")
    )


def _looks_like_role_target(log_type: str, title: str) -> bool:
    text = _plain(title)
    if log_type != "roles" or "membre" in text or "attribue" in text or "retire" in text:
        return False
    return "role" in text and not re.search(r"(?:creation|suppression|modification) de roles \d+", text)


def _looks_like_channel_target(log_type: str, title: str) -> bool:
    return log_type == "server" and "salon" in _plain(title)


def _is_message_target(log_type: str, title: str) -> bool:
    return log_type == "messages" or "message" in _plain(title)


def enrich_embed(bot: commands.Bot, guild: discord.Guild, log_type: str, source: discord.Embed) -> discord.Embed:
    """Ajoute seulement le contexte utile ; pas de gros blocs serveur/date verticaux."""
    embed = _sanitize_embed(bot, guild, source)
    title = str(embed.title or "Log SentriX")
    target_id = _footer_target(embed)

    if target_id:
        if _is_message_target(log_type, title):
            # L'ID est déjà dans le footer/bouton : ne pas ajouter une section verticale.
            pass
        elif _looks_like_role_target(log_type, title):
            _add_field(embed, "🏷️ Rôle", _role_context(guild, target_id, embed))
        elif _looks_like_channel_target(log_type, title):
            _add_field(embed, "#️⃣ Salon", _channel_context(guild, target_id, embed))
        elif _looks_like_member_target(log_type, title):
            _add_field(embed, "👤 Cible", _user_context(bot, guild, target_id))

    grouped = re.search(r"(?:Création|Suppression|Modification) de rôles \((\d+)\)", title, re.IGNORECASE)
    if grouped and not _field_exists(embed, "📦 Rafale"):
        _add_field(embed, "📦 Rafale", f"**{grouped.group(1)} rôles** regroupés dans la même fenêtre fixe de **3 secondes**.")

    return embed


def _event_kind(embed: discord.Embed, log_type: str) -> str:
    sample = " ".join(
        [str(embed.title or ""), str(embed.description or "")]
        + [str(field.name) for field in embed.fields]
    )
    plain = _plain(sample[:3000])
    for marker in EVENT_MARKERS:
        if marker in plain:
            return marker
    title = _plain(str(embed.title or ""))
    return title[:80] or log_type


def _fingerprint(guild: discord.Guild, log_type: str, embed: discord.Embed) -> str:
    target_id = _footer_target(embed)
    kind = _event_kind(embed, log_type)
    if target_id:
        raw = f"{guild.id}:{log_type}:{kind}:{target_id}"
    else:
        # Sans cible stable, inclure le contenu normalisé pour ne pas fusionner deux vrais
        # événements différents arrivés au même moment.
        body = "|".join(
            [str(embed.title or ""), str(embed.description or "")]
            + [f"{field.name}:{field.value}" for field in embed.fields]
        )
        digest = hashlib.sha1(_plain(body).encode("utf-8", "ignore")).hexdigest()[:16]
        raw = f"{guild.id}:{log_type}:{kind}:{digest}"
    return raw


def _is_duplicate(guild: discord.Guild, log_type: str, embed: discord.Embed) -> bool:
    now = time.monotonic()
    stale = [key for key, expires in _RECENT_LOGS.items() if expires <= now]
    for key in stale[:2000]:
        _RECENT_LOGS.pop(key, None)

    key = _fingerprint(guild, log_type, embed)
    if _RECENT_LOGS.get(key, 0.0) > now:
        return True
    _RECENT_LOGS[key] = now + DEDUPE_TTL_SECONDS
    if len(_RECENT_LOGS) > 10000:
        for old_key in list(_RECENT_LOGS)[:2000]:
            _RECENT_LOGS.pop(old_key, None)
    return False


def _thumbnail_url(embed: discord.Embed, bot: commands.Bot, guild: discord.Guild) -> str | None:
    thumb = getattr(embed.thumbnail, "url", None)
    if thumb:
        return str(thumb)
    if guild.icon:
        return str(guild.icon.url)
    if bot.user:
        return str(bot.user.display_avatar.url)
    return None


def _ordered_fields(embed: discord.Embed):
    try:
        return premium_logs_v2._ordered_fields(embed)
    except Exception:
        return list(embed.fields)


def _compact_paragraph(field: discord.EmbedProxy) -> str:
    name = str(field.name).strip() or "Détail"
    value = str(field.value).strip() or "*Aucune information disponible.*"
    # Les contenus longs restent accessibles sans transformer chaque petit log en page.
    return f"### {name[:100]}\n{value[:900]}"


def _detail_blocks(embed: discord.Embed, *, grouped_roles: bool) -> list[str]:
    paragraphs = [_compact_paragraph(field) for field in _ordered_fields(embed)]
    if not paragraphs:
        return []

    # 6 sections suffisent pour le détail normal. Les batches rôles gardent leur grande
    # liste dans la description, donc les champs complémentaires restent très courts.
    paragraphs = paragraphs[:6]
    blocks: list[str] = []
    current = ""
    limit = 1700 if not grouped_roles else 1200
    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                blocks.append(current)
            current = paragraph
    if current:
        blocks.append(current)
    return blocks[:2]


class DetailedPremiumLogLayout(discord.ui.LayoutView):
    """Carte large/compacte : header + avatar, détails groupés, footer et boutons."""

    _sentrix_log_layout = True

    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        buttons: list[tuple[str, int]],
    ):
        super().__init__(timeout=6 * 60 * 60)
        detailed = enrich_embed(bot, guild, log_type, embed)
        accent = int(detailed.colour.value) if detailed.colour else 0x7C5CFC
        category = CATEGORY_LABELS.get(log_type, log_type.upper())
        title = str(detailed.title or "Journal SentriX").strip()
        grouped_roles = bool(re.search(r"rôles \(\d+\)", title, re.IGNORECASE))

        container = discord.ui.Container(accent_colour=accent)
        header_lines = [
            f"-# 🛡️ SENTRIX  •  {category}  •  {guild.name}",
            f"# {title}",
        ]
        description = (detailed.description or "").strip()
        # Pour une rafale de rôles la description EST la liste : elle doit rester pleine
        # largeur sous le séparateur au lieu d'être écrasée à côté du thumbnail.
        if description and not grouped_roles:
            header_lines.append(description[:900])

        header = discord.ui.TextDisplay("\n".join(header_lines)[:3900])
        thumbnail = _thumbnail_url(detailed, bot, guild)
        if thumbnail:
            container.add_item(
                discord.ui.Section(
                    header,
                    accessory=discord.ui.Thumbnail(thumbnail, description="Identité du journal SentriX"),
                )
            )
        else:
            container.add_item(header)

        if grouped_roles and description:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(description[:3900]))

        blocks = _detail_blocks(detailed, grouped_roles=grouped_roles)
        for block in blocks:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(block))

        image_url = getattr(detailed.image, "url", None)
        if image_url:
            gallery = discord.ui.MediaGallery()
            gallery.add_item(media=str(image_url), description=f"Aperçu — {title[:80]}")
            container.add_item(discord.ui.Separator())
            container.add_item(gallery)

        container.add_item(discord.ui.Separator())
        event_ts = _event_timestamp(detailed)
        target_id = _footer_target(detailed)
        footer = f"-# SentriX • Journal sécurisé • <t:{event_ts}:R>"
        if target_id:
            footer += f" • ID `{target_id}`"
        container.add_item(discord.ui.TextDisplay(footer))

        final_buttons = _button_items(detailed, title) or buttons
        if final_buttons:
            row = discord.ui.ActionRow()
            seen: set[tuple[str, int]] = set()
            for index, (label, value) in enumerate(final_buttons[:5]):
                key = (str(label), int(value))
                if key in seen:
                    continue
                seen.add(key)
                row.add_item(premium_logs_v2.CopyIdButton(str(label), int(value), index))
            if row.children:
                container.add_item(row)

        self.add_item(container)


def _reset_file(file: discord.File | None) -> None:
    if file is None:
        return
    try:
        file.reset(seek=True)
    except Exception:
        pass


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del extension_name
    global _INSTALLED
    if _INSTALLED:
        return

    if not all(hasattr(discord.ui, name) for name in ("LayoutView", "Container", "Section", "TextDisplay")):
        logger.warning("V24 : Components V2 indisponibles ; layout premium compact ignoré.")
        return

    DetailedPremiumLogLayout._sentrix_detailed_v24 = True
    premium_logs_v2.PremiumLogLayout = DetailedPremiumLogLayout

    previous_send = log_service.send_log
    if not getattr(previous_send, "_sentrix_compact_unique_logs_v24", False):
        async def send_compact_unique_log(
            inner_bot,
            guild: discord.Guild,
            log_type: str,
            embed: discord.Embed,
            file: discord.File | None = None,
        ) -> bool:
            # Protection cross-process Railway.
            if not _is_primary_log_service():
                return True

            # Protection intra-process contre deux listeners historiques qui décrivent le
            # même événement avec deux cartes légèrement différentes.
            if _is_duplicate(guild, log_type, embed):
                logger.debug("V24 : doublon log supprimé guild=%s type=%s", guild.id, log_type)
                return True

            # Toujours travailler avec une copie sans syntaxe de mention Discord.
            safe_embed = _sanitize_embed(inner_bot, guild, embed)

            if file is None:
                return await previous_send(inner_bot, guild, log_type, safe_embed, file=None)

            try:
                styled = style_log(inner_bot, guild, log_type, safe_embed)
                premium_logs_v2._fix_timeout_duration(styled, safe_embed)
                styled = enrich_embed(inner_bot, guild, log_type, styled)
                buttons = _button_items(styled, str(styled.title or ""))

                setting = await log_service.get_log_setting(inner_bot, guild.id, log_type)
                if not setting["enabled"]:
                    return False
                ok, _reason = log_service.validate_channel(guild, setting["channel_id"], needs_file=True)
                if not ok:
                    return False
                channel = guild.get_channel(setting["channel_id"])
                if not isinstance(channel, discord.TextChannel):
                    return False

                layout = DetailedPremiumLogLayout(inner_bot, guild, log_type, styled, buttons)
                _reset_file(file)
                await channel.send(
                    view=layout,
                    file=file,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True
            except Exception:
                logger.exception("V24 : log avec fichier refusé (%s).", log_type)
                return False

        send_compact_unique_log._sentrix_compact_unique_logs_v24 = True
        send_compact_unique_log._sentrix_original = previous_send
        log_service.send_log = send_compact_unique_log

    _INSTALLED = True
    logger.info(
        "V24 : logs compacts uniques actifs (primary=%s, dedupe=%.0fs, mentions=off).",
        _is_primary_log_service(),
        DEDUPE_TTL_SECONDS,
    )


__all__ = ["install", "enrich_embed", "DetailedPremiumLogLayout"]
