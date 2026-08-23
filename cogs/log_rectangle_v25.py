"""SentriX V25 — rendu final des logs en rectangle horizontal + anti-doublon de sortie.

Cette couche est volontairement installée APRES V24. Elle ne recrée aucun listener :
elle remplace seulement le renderer final Components V2 et protège TextChannel.send au
dernier moment. Cela permet de bloquer un doublon même lorsqu'un ancien listener contourne
une couche intermédiaire du moteur de logs.

Objectif visuel : carte proche du ratio 1268 x 552 demandé. Discord fixe lui-même la
largeur/hauteur en pixels ; on réduit donc le nombre de blocs verticaux à trois :
1) section horizontale header + grand titre + résumé, avec avatar à droite ;
2) un seul bloc compact d'informations ;
3) footer + boutons ID.
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

from . import premium_logs_v2
from .premium_logs import _button_items

logger = logging.getLogger("bot.log-rectangle-v25")
_INSTALLED = False

PRIMARY_RAILWAY_SERVICE_ID = "d4fb0c3a-d62b-4817-aae1-3cfc859d32c0"
OUTPUT_DEDUPE_TTL = 8.0
_OUTPUT_RECENT: dict[str, float] = {}

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

EVENT_EMOJI = {
    "message supprime": "🗑️",
    "message modifie": "✏️",
    "role cree": "🏷️",
    "role supprime": "🏷️",
    "role modifie": "🏷️",
    "creation de roles": "🏷️",
    "suppression de roles": "🏷️",
    "modification de roles": "🏷️",
    "membre banni": "🔨",
    "bannissement": "🔨",
    "membre debanni": "🔓",
    "kick": "👢",
    "timeout": "⏱️",
    "mute": "🔇",
    "warn": "⚠️",
    "salon cree": "💬",
    "salon supprime": "💬",
    "salon modifie": "💬",
    "ticket": "🎫",
}

IMPORTANT_FIELDS = (
    "auteur", "salon", "contenu", "membre", "utilisateur", "cible", "effectue par",
    "moderateur", "acteur", "raison", "raison audit log", "duree", "role", "avant",
    "apres", "pieces jointes", "acces", "action",
)


def _plain(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _first_id(value: str | None) -> int | None:
    match = re.search(r"(?<!\d)(\d{15,22})(?!\d)", value or "")
    return int(match.group(1)) if match else None


def _target_id(embed: discord.Embed) -> int | None:
    footer = getattr(getattr(embed, "footer", None), "text", None)
    value = _first_id(footer)
    if value:
        return value
    for field in embed.fields:
        value = _first_id(str(field.value))
        if value:
            return value
    return None


def _event_kind_from_text(value: str) -> str:
    plain = _plain(value)
    for marker in EVENT_EMOJI:
        if marker in plain:
            return marker
    if "message" in plain and "supprim" in plain:
        return "message supprime"
    if "role" in plain and "cre" in plain:
        return "role cree"
    if "ban" in plain:
        return "bannissement"
    return plain[:80] or "journal"


def _event_kind(embed: discord.Embed) -> str:
    sample = " ".join(
        [str(embed.title or ""), str(embed.description or "")]
        + [f"{field.name} {field.value}" for field in embed.fields]
    )
    return _event_kind_from_text(sample[:6000])


def _fingerprint_embed(guild_id: int, embed: discord.Embed) -> str:
    kind = _event_kind(embed)
    target = _target_id(embed)
    if target:
        return f"{guild_id}:{kind}:{target}"
    body = "|".join(
        [str(embed.title or ""), str(embed.description or "")]
        + [f"{field.name}:{field.value}" for field in embed.fields]
    )
    digest = hashlib.sha1(_plain(body).encode("utf-8", "ignore")).hexdigest()[:18]
    return f"{guild_id}:{kind}:{digest}"


def _remember_output(key: str) -> bool:
    now = time.monotonic()
    if len(_OUTPUT_RECENT) > 6000:
        for old_key, expires in list(_OUTPUT_RECENT.items())[:2000]:
            if expires <= now:
                _OUTPUT_RECENT.pop(old_key, None)
    if _OUTPUT_RECENT.get(key, 0.0) > now:
        return False
    _OUTPUT_RECENT[key] = now + OUTPUT_DEDUPE_TTL
    return True


def _is_primary_process() -> bool:
    service_id = (os.getenv("RAILWAY_SERVICE_ID") or "").strip()
    if service_id:
        wanted = (os.getenv("SENTRIX_LOG_PRIMARY_SERVICE_ID") or PRIMARY_RAILWAY_SERVICE_ID).strip()
        return service_id == wanted
    # Hors Railway, on ne désactive pas les logs.
    return True


def _display_user(bot: commands.Bot, guild: discord.Guild, user_id: int) -> str:
    member = guild.get_member(user_id)
    user = member or bot.get_user(user_id)
    if user is None:
        return f"@Utilisateur-{user_id}"
    name = getattr(user, "display_name", None) or getattr(user, "name", None) or str(user)
    safe = discord.utils.escape_markdown(str(name).replace("`", "'").replace("@", "＠"))
    return "@" + safe


def _display_role(guild: discord.Guild, role_id: int) -> str:
    role = guild.get_role(role_id)
    name = role.name if role is not None else f"Rôle-{role_id}"
    safe = discord.utils.escape_markdown(str(name).replace("`", "'").replace("@", "＠"))
    return "@" + safe


def _display_channel(guild: discord.Guild, channel_id: int) -> str:
    channel = guild.get_channel(channel_id)
    name = channel.name if channel is not None else f"salon-{channel_id}"
    return "#" + discord.utils.escape_markdown(str(name).replace("`", "'"))


def _deping(bot: commands.Bot, guild: discord.Guild, value: str | None) -> str:
    text = str(value or "")
    text = re.sub(r"<@!?(\d{15,22})>", lambda m: _display_user(bot, guild, int(m.group(1))), text)
    text = re.sub(r"<@&(\d{15,22})>", lambda m: _display_role(guild, int(m.group(1))), text)
    text = re.sub(r"<#(\d{15,22})>", lambda m: _display_channel(guild, int(m.group(1))), text)
    return text


def _sanitized_embed(bot: commands.Bot, guild: discord.Guild, source: discord.Embed) -> discord.Embed:
    embed = source.copy()
    if embed.title:
        embed.title = _deping(bot, guild, embed.title)[:256]
    if embed.description:
        embed.description = _deping(bot, guild, embed.description)[:4096]
    for index, field in enumerate(list(embed.fields)):
        embed.set_field_at(
            index,
            name=_deping(bot, guild, str(field.name))[:256],
            value=_deping(bot, guild, str(field.value))[:1024],
            inline=False,
        )
    return embed


def _event_title(embed: discord.Embed) -> str:
    raw = str(embed.title or "Journal SentriX").strip()
    plain = _plain(raw)
    if raw and raw[0] in "🗑️✏️🏷️🔨🔓👢⏱️🔇⚠️💬🎫👤🔊🛡️📋":
        return raw
    emoji = "📋"
    for marker, candidate in EVENT_EMOJI.items():
        if marker in plain:
            emoji = candidate
            break
    return f"{emoji} {raw}"


def _avatar_url(bot: commands.Bot, guild: discord.Guild, embed: discord.Embed) -> str | None:
    # Priorité à l'auteur/cible du log quand son ID est présent dans un champ.
    for field in embed.fields:
        name = _plain(str(field.name))
        if not any(token in name for token in ("auteur", "membre", "utilisateur", "cible", "moderateur", "acteur")):
            continue
        user_id = _first_id(str(field.value))
        if not user_id:
            continue
        member = guild.get_member(user_id)
        user = member or bot.get_user(user_id)
        if user is not None:
            return str(user.display_avatar.url)
    thumb = getattr(embed.thumbnail, "url", None)
    if thumb:
        return str(thumb)
    if guild.icon:
        return str(guild.icon.url)
    if bot.user:
        return str(bot.user.display_avatar.url)
    return None


def _is_role_batch(embed: discord.Embed) -> bool:
    title = _plain(str(embed.title or ""))
    return bool(re.search(r"(?:creation|suppression|modification) de roles \d+", title)) or (
        "de roles" in title and any(token in title for token in ("creation", "suppression", "modification"))
    )


def _compact_value(value: str, limit: int = 480) -> str:
    value = re.sub(r"\n{3,}", "\n\n", value.strip())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _body_text(embed: discord.Embed) -> str:
    # Pour une rafale de rôles, la liste est la donnée principale : on la garde complète
    # dans UN seul bloc au lieu de créer une case par rôle.
    if _is_role_batch(embed):
        description = (embed.description or "").strip()
        parts = [description[:3600]] if description else []
        for field in embed.fields[:2]:
            parts.append(f"**{field.name}**  {_compact_value(str(field.value), 500)}")
        return "\n\n".join(part for part in parts if part)[:3900]

    selected = []
    seen = set()
    for field in embed.fields:
        name_plain = _plain(str(field.name))
        if any(token in name_plain for token in IMPORTANT_FIELDS):
            key = name_plain[:50]
            if key in seen:
                continue
            seen.add(key)
            selected.append(field)
        if len(selected) >= 4:
            break

    if not selected:
        selected = list(embed.fields[:3])

    lines: list[str] = []
    for field in selected:
        name = str(field.name).strip()
        value = _compact_value(str(field.value), 420)
        # Compact : une information = un paragraphe court, pas une section V2 distincte.
        lines.append(f"**{name}**\n{value}")
    return "\n\n".join(lines)[:3000]


def _header_text(guild: discord.Guild, log_type: str, embed: discord.Embed) -> str:
    category = CATEGORY_LABELS.get(log_type, log_type.upper())
    title = _event_title(embed)
    description = (embed.description or "").strip()
    # Sur un batch de rôles, la longue liste va dans le bloc inférieur pour garder le header bas.
    if _is_role_batch(embed):
        description = "Plusieurs rôles ont été détectés dans la même fenêtre de 3 secondes."
    if description:
        description = _compact_value(description, 620)
        return f"-# 🛡️ SENTRIX • {category} • {guild.name}\n# {title}\n{description}"
    return f"-# 🛡️ SENTRIX • {category} • {guild.name}\n# {title}"


def _event_timestamp(embed: discord.Embed) -> int:
    stamp = embed.timestamp
    if stamp is None:
        stamp = datetime.now(timezone.utc)
    elif stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return int(stamp.timestamp())


class RectangleLogLayout(discord.ui.LayoutView):
    """Carte finale large et peu haute : une Section + un bloc + footer."""

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
        accent = int(clean.colour.value) if clean.colour else 0x7C5CFC
        container = discord.ui.Container(accent_colour=accent)

        header = discord.ui.TextDisplay(_header_text(guild, log_type, clean))
        avatar = _avatar_url(bot, guild, clean)
        if avatar:
            container.add_item(
                discord.ui.Section(
                    header,
                    accessory=discord.ui.Thumbnail(avatar, description="Identité du journal SentriX"),
                )
            )
        else:
            container.add_item(header)

        body = _body_text(clean)
        if body:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(body))

        container.add_item(discord.ui.Separator())
        event_ts = _event_timestamp(clean)
        target = _target_id(clean)
        footer = f"-# SentriX • Journal sécurisé • <t:{event_ts}:R>"
        if target:
            footer += f" • ID `{target}`"
        container.add_item(discord.ui.TextDisplay(footer))

        final_buttons = _button_items(clean, str(clean.title or "")) or buttons
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

        self._sentrix_log_fingerprint = _fingerprint_embed(guild.id, clean)
        self._sentrix_is_log_layout = True
        self.add_item(container)


def _looks_like_log_embed(embed: discord.Embed | None) -> bool:
    if embed is None:
        return False
    sample = " ".join(
        [str(embed.title or ""), str(embed.description or ""), str(getattr(embed.footer, "text", "") or "")]
        + [str(field.name) for field in embed.fields]
    )
    plain = _plain(sample)
    if "sentrix" in plain and ("journal" in plain or "log" in plain):
        return True
    return any(marker in plain for marker in EVENT_EMOJI)


def _output_fingerprint(channel: discord.TextChannel, args, kwargs) -> str | None:
    view = kwargs.get("view")
    if view is not None:
        fp = getattr(view, "_sentrix_log_fingerprint", None)
        if fp:
            return str(fp)

    embed = kwargs.get("embed")
    if embed is None:
        for arg in args:
            if isinstance(arg, discord.Embed):
                embed = arg
                break
    if isinstance(embed, discord.Embed) and _looks_like_log_embed(embed):
        return _fingerprint_embed(channel.guild.id, embed)
    return None


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del bot, extension_name
    global _INSTALLED
    if _INSTALLED:
        return

    if not all(hasattr(discord.ui, name) for name in ("LayoutView", "Container", "Section", "TextDisplay", "Thumbnail")):
        logger.warning("V25 logs rectangle indisponible : Components V2 manquants.")
        return

    # Dernier renderer : premium_logs_v2 le résout dynamiquement au moment de l'envoi.
    premium_logs_v2.PremiumLogLayout = RectangleLogLayout

    previous_send = discord.TextChannel.send
    if not getattr(previous_send, "_sentrix_output_dedupe_v25", False):
        async def send_with_final_log_guard(self: discord.TextChannel, *args, **kwargs):
            fingerprint = _output_fingerprint(self, args, kwargs)
            if fingerprint is not None:
                # Protection inter-service au niveau de la sortie Discord elle-même.
                if not _is_primary_process():
                    return None
                # Protection intra-process : même un ancien listener qui contourne V24
                # ne peut plus publier une seconde carte du même événement.
                if not _remember_output(fingerprint):
                    logger.debug("V25 : doublon log bloqué dans #%s (%s).", self.name, fingerprint)
                    return None
                kwargs["allowed_mentions"] = discord.AllowedMentions.none()
            return await previous_send(self, *args, **kwargs)

        send_with_final_log_guard._sentrix_output_dedupe_v25 = True
        send_with_final_log_guard._sentrix_original = previous_send
        discord.TextChannel.send = send_with_final_log_guard

    _INSTALLED = True
    logger.info(
        "V25 logs : rectangle horizontal final + anti-doublon sortie 8 s + zéro ping actifs (primaire=%s).",
        _is_primary_process(),
    )


__all__ = ["install", "RectangleLogLayout"]
