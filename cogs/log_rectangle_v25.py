"""SentriX V25 — sortie unique des logs, rectangle horizontal compact.

Cette couche est le dernier point de rendu des journaux Discord.

Garanties :
- un seul service Railway publie les logs ;
- les anciens layouts V2/V24 sont bloqués quand V25 est disponible ;
- une seule carte V25 par événement pendant la fenêtre de déduplication ;
- aucun ping membre/rôle ;
- les mentions de salons <#id> restent intactes et donc cliquables ;
- aucun thumbnail/image automatique : le journal reste bas et horizontal.

Discord ne permet pas d'imposer une taille pixel exacte à un composant. Le layout est donc
volontairement réduit à un seul TextDisplay + éventuellement une rangée de boutons afin de
se rapprocher d'un rectangle d'environ 552 px de large pour ~268 px de haut sur desktop.
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

# Source de vérité : seul CE service Railway publie les journaux Discord.
# Ne pas permettre à une variable d'environnement ancienne de remplacer cet ID : c'était
# précisément une source possible de doubles publications entre les deux services.
PRIMARY_RAILWAY_SERVICE_ID = "d4fb0c3a-d62b-4817-aae1-3cfc859d32c0"
PRIMARY_RAILWAY_SERVICE_NAME = "mon-bot-discord"
OUTPUT_DEDUPE_TTL = 10.0
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
    "membre arrive": "📥",
    "membre parti": "📤",
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
    "vocal": "🎙️",
}


def _plain(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _first_id(value: str | None) -> int | None:
    match = re.search(r"(?<!\d)(\d{15,22})(?!\d)", value or "")
    return int(match.group(1)) if match else None


def _field_value(embed: discord.Embed, *tokens: str) -> str:
    wanted = tuple(_plain(token) for token in tokens)
    for field in embed.fields:
        name = _plain(str(field.name))
        if any(token in name for token in wanted):
            return str(field.value)
    return ""


def _target_id(embed: discord.Embed) -> int | None:
    footer = getattr(getattr(embed, "footer", None), "text", None)
    return _first_id(footer)


def _event_kind_from_text(value: str) -> str:
    plain = _plain(value)
    for marker in EVENT_EMOJI:
        if marker in plain:
            return marker
    if "message" in plain and "supprim" in plain:
        return "message supprime"
    if "message" in plain and "modifi" in plain:
        return "message modifie"
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


def _message_semantic_key(guild_id: int, embed: discord.Embed, kind: str) -> str:
    author_value = _field_value(embed, "auteur")
    salon_value = _field_value(embed, "salon")
    content_value = _field_value(embed, "contenu", "avant", "apres")

    author_id = _first_id(author_value)
    channel_id = _first_id(salon_value)
    if channel_id is None:
        channel_match = re.search(r"<#(\d{15,22})>", salon_value)
        channel_id = int(channel_match.group(1)) if channel_match else None

    author_key = str(author_id or _plain(author_value)[:80])
    channel_key = str(channel_id or _plain(salon_value)[:100])
    content_key = hashlib.sha1(_plain(content_value).encode("utf-8", "ignore")).hexdigest()[:14]
    return f"{guild_id}:messages:{kind}:{author_key}:{channel_key}:{content_key}"


def _fingerprint_embed(guild_id: int, embed: discord.Embed) -> str:
    kind = _event_kind(embed)
    if kind in {"message supprime", "message modifie"}:
        return _message_semantic_key(guild_id, embed, kind)

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
    stale = [item for item, expires in _OUTPUT_RECENT.items() if expires <= now]
    for item in stale[:2000]:
        _OUTPUT_RECENT.pop(item, None)

    if _OUTPUT_RECENT.get(key, 0.0) > now:
        return False
    _OUTPUT_RECENT[key] = now + OUTPUT_DEDUPE_TTL
    if len(_OUTPUT_RECENT) > 8000:
        for item in list(_OUTPUT_RECENT)[:2000]:
            _OUTPUT_RECENT.pop(item, None)
    return True


def _is_primary_process() -> bool:
    """Bloque fermement le second service Railway pour les journaux.

    En local/CI sans variables Railway, les logs restent actifs pour ne pas casser les tests.
    """
    service_id = (os.getenv("RAILWAY_SERVICE_ID") or "").strip()
    if service_id:
        return service_id == PRIMARY_RAILWAY_SERVICE_ID

    service_name = (os.getenv("RAILWAY_SERVICE_NAME") or "").strip().casefold()
    if service_name:
        return service_name == PRIMARY_RAILWAY_SERVICE_NAME or service_name.endswith(
            " - " + PRIMARY_RAILWAY_SERVICE_NAME
        )

    if (os.getenv("RAILWAY_PROJECT_ID") or "").strip():
        # Un environnement Railway sans identité de service ne doit jamais devenir une
        # deuxième source de logs par défaut.
        return False
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


def _deping_people(bot: commands.Bot, guild: discord.Guild, value: str | None) -> str:
    """Dé-ping uniquement membres/rôles. Les <#salons> restent cliquables."""
    text = str(value or "")
    text = re.sub(r"<@!?(\d{15,22})>", lambda m: _display_user(bot, guild, int(m.group(1))), text)
    text = re.sub(r"<@&(\d{15,22})>", lambda m: _display_role(guild, int(m.group(1))), text)
    return text


def _sanitized_embed(bot: commands.Bot, guild: discord.Guild, source: discord.Embed) -> discord.Embed:
    embed = source.copy()
    if embed.title:
        embed.title = _deping_people(bot, guild, embed.title)[:256]
    if embed.description:
        embed.description = _deping_people(bot, guild, embed.description)[:4096]
    for index, field in enumerate(list(embed.fields)):
        embed.set_field_at(
            index,
            name=_deping_people(bot, guild, str(field.name))[:256],
            value=_deping_people(bot, guild, str(field.value))[:1024],
            inline=False,
        )
    return embed


def _event_title(embed: discord.Embed) -> str:
    raw = str(embed.title or "Journal SentriX").strip()
    # Enlève seulement un éventuel double espace ; on garde le titre métier exact.
    raw = re.sub(r"\s+", " ", raw)
    plain = _plain(raw)
    if raw and any(raw.startswith(emoji) for emoji in EVENT_EMOJI.values()):
        return raw
    emoji = "📋"
    for marker, candidate in EVENT_EMOJI.items():
        if marker in plain:
            emoji = candidate
            break
    return f"{emoji} {raw}"


def _one_line(value: str, limit: int) -> str:
    value = re.sub(r"\s*\n\s*", " · ", value.strip())
    value = re.sub(r"\s{2,}", " ", value)
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _first_line_without_id(value: str, limit: int = 110) -> str:
    if not value:
        return "Inconnu"
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return "Inconnu"
    # Le premier élément est généralement le nom/mention lisible. L'ID reste dans le
    # footer/bouton, ce qui évite de gonfler la carte.
    return _one_line(lines[0], limit)


def _is_role_batch(embed: discord.Embed) -> bool:
    title = _plain(str(embed.title or ""))
    return "de roles" in title and any(token in title for token in ("creation", "suppression", "modification"))


def _compact_text(guild: discord.Guild, log_type: str, embed: discord.Embed) -> str:
    category = CATEGORY_LABELS.get(log_type, log_type.upper())
    title = _event_title(embed)
    event_ts = _event_timestamp(embed)
    target = _target_id(embed)

    lines = [
        f"-# 🛡️ SENTRIX • {category} • {guild.name}",
        f"## {title}",
    ]

    if _is_role_batch(embed):
        description = (embed.description or "").strip()
        if description:
            lines.append(description[:3000])
    else:
        author = _field_value(embed, "auteur", "membre", "utilisateur", "cible")
        salon = _field_value(embed, "salon")
        actor = _field_value(embed, "effectue par", "moderateur", "acteur")
        reason = _field_value(embed, "raison")
        duration = _field_value(embed, "duree", "fin du timeout", "nouvel etat")
        content = _field_value(embed, "contenu")
        before = _field_value(embed, "avant")
        after = _field_value(embed, "apres")

        identity_parts: list[str] = []
        if author:
            identity_parts.append(f"👤 **Auteur** {_first_line_without_id(author)}")
        if salon:
            # `salon` contient volontairement encore <#id> pour un vrai lien Discord.
            identity_parts.append(f"💬 **Salon** {_first_line_without_id(salon, 140)}")
        if identity_parts:
            lines.append("  •  ".join(identity_parts))

        if content:
            lines.append(f"📝 **Contenu** {_one_line(content, 360)}")
        elif before or after:
            if before:
                lines.append(f"◀️ **Avant** {_one_line(before, 210)}")
            if after:
                lines.append(f"▶️ **Après** {_one_line(after, 210)}")
        else:
            description = (embed.description or "").strip()
            if description:
                lines.append(_one_line(description, 420))

        extra_parts: list[str] = []
        if actor:
            extra_parts.append(f"🛡️ {_first_line_without_id(actor, 120)}")
        if reason:
            extra_parts.append(f"📝 {_one_line(reason, 180)}")
        if duration:
            extra_parts.append(f"⏱️ {_one_line(duration, 160)}")
        if extra_parts:
            lines.append("  •  ".join(extra_parts))

    footer = f"-# SentriX • <t:{event_ts}:R>"
    if target:
        footer += f" • ID `{target}`"
    lines.append(footer)
    return "\n".join(lines)[:3900]


def _event_timestamp(embed: discord.Embed) -> int:
    stamp = embed.timestamp
    if stamp is None:
        stamp = datetime.now(timezone.utc)
    elif stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return int(stamp.timestamp())


class RectangleLogLayout(discord.ui.LayoutView):
    """Un seul bloc de texte : le rendu le plus horizontal possible dans Discord."""

    _sentrix_log_layout = True
    _sentrix_rectangle_v25 = True

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

        # Pas de Section, pas de Thumbnail, pas de Separator : hauteur minimale.
        container.add_item(discord.ui.TextDisplay(_compact_text(guild, log_type, clean)))

        final_buttons = _button_items(clean, str(clean.title or "")) or buttons
        if final_buttons:
            row = discord.ui.ActionRow()
            seen: set[tuple[str, int]] = set()
            for index, (label, value) in enumerate(final_buttons[:3]):
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


def _is_log_view(view) -> bool:
    if view is None:
        return False
    cls = view.__class__
    module = str(getattr(cls, "__module__", ""))
    name = str(getattr(cls, "__name__", ""))
    return bool(
        getattr(view, "_sentrix_is_log_layout", False)
        or getattr(cls, "_sentrix_log_layout", False)
        or name in {"PremiumLogLayout", "DetailedPremiumLogLayout", "RectangleLogLayout"}
        or module.endswith("premium_logs_v2")
        # log_detail_layout_v24 supprime : plus aucune vue ne peut venir de ce module.
        or module.endswith("log_rectangle_v25")
    )


def _is_legacy_log_view(view) -> bool:
    if not _is_log_view(view):
        return False
    return not bool(
        getattr(view, "_sentrix_rectangle_v25", False)
        or getattr(view.__class__, "_sentrix_rectangle_v25", False)
    )


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


def _has_file(kwargs) -> bool:
    return kwargs.get("file") is not None or bool(kwargs.get("files"))


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del bot, extension_name
    global _INSTALLED

    # IMPORTANT : même lors des appels suivants, on remet V25 comme renderer final. Cela
    # empêche une couche chargée plus tard de rétablir PremiumLogLayout/Detailed V24.
    if all(hasattr(discord.ui, name) for name in ("LayoutView", "Container", "TextDisplay")):
        premium_logs_v2.PremiumLogLayout = RectangleLogLayout
    else:
        logger.warning("V25 logs rectangle indisponible : Components V2 manquants.")
        return

    if _INSTALLED:
        return

    previous_send = discord.TextChannel.send
    if not getattr(previous_send, "_sentrix_output_dedupe_v25", False):
        async def send_with_final_log_guard(self: discord.TextChannel, *args, **kwargs):
            view = kwargs.get("view")
            embed = kwargs.get("embed")
            is_log_output = _is_log_view(view) or (
                isinstance(embed, discord.Embed) and _looks_like_log_embed(embed)
            )

            if is_log_output:
                # Le deuxième Railway n'a plus aucune possibilité de publier une ancienne
                # carte, même si elle ne possède pas l'empreinte V25.
                if not _is_primary_process():
                    return None

                # V24/V2 ne doivent plus apparaître en parallèle du rectangle V25.
                # Exception fichiers/transcripts : tant qu'ils utilisent encore le chemin
                # historique, on ne sacrifie pas la pièce jointe.
                if _is_legacy_log_view(view) and not _has_file(kwargs):
                    logger.debug("V25 : ancien layout de log bloqué dans #%s.", self.name)
                    return None

                fingerprint = _output_fingerprint(self, args, kwargs)
                if fingerprint is not None and not _remember_output(fingerprint):
                    logger.debug("V25 : doublon log bloqué dans #%s (%s).", self.name, fingerprint)
                    return None

                # Aucun membre/rôle n'est mentionné ; les <#salons> restent cliquables.
                kwargs["allowed_mentions"] = discord.AllowedMentions.none()

            return await previous_send(self, *args, **kwargs)

        send_with_final_log_guard._sentrix_output_dedupe_v25 = True
        send_with_final_log_guard._sentrix_original = previous_send
        discord.TextChannel.send = send_with_final_log_guard

    _INSTALLED = True
    logger.info(
        "V25 logs : renderer rectangle unique, anciens layouts bloqués, salon cliquable, "
        "images retirées, service primaire=%s.",
        _is_primary_process(),
    )


__all__ = ["install", "RectangleLogLayout"]
