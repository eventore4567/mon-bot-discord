"""Renderer Components V2 et historique SQLite des journaux SentriX.

Le transport reste strictement Components V2 : bannière en premier, bloc identité,
bloc événement narratif, puis actions. Aucun fallback ``channel.send(embed=...)``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import traceback
from pathlib import Path
from typing import Any

import aiosqlite
import discord

import config
from utils.log_banners import COLORS, get_banner
from utils.log_categories import (
    DEFAULT_EVENT_EMOJI,
    EVENT_EMOJI,
    canonical_event_type,
    category_for,
    resolve,
)

logger = logging.getLogger("bot.wide-logs")

NO_PINGS = discord.AllowedMentions(everyone=False, users=False, roles=False, replied_user=False)
FALLBACK_ENABLED = False
_RUNTIME_CHECKED = False
_DB_READY = False

_MENTION_RE = re.compile(r"@(everyone|here)\b", re.IGNORECASE)
_SNOWFLAKE_RE = re.compile(r"(?<!\d)(\d{15,22})(?!\d)")
_CHANNEL_MENTION_RE = re.compile(r"<#\d{15,22}>")
_USER_MENTION_RE = re.compile(r"<@!?\d{15,22}>")
_ROLE_MENTION_RE = re.compile(r"<@&\d{15,22}>")
_DECORATIVE_LINE_RE = re.compile(r"^[\s━─═—–_\-•·┄┈┉┅┇]{4,}$")

_TARGET_LABELS = (
    "auteur", "author", "cible", "target", "membre", "member", "utilisateur",
    "user", "victime", "rôle", "role", "salon", "channel",
)
_MODERATOR_LABELS = (
    "modérateur", "moderateur", "moderator", "staff", "exécuteur", "executeur",
    "executor", "acteur", "actor", "responsable",
)

_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    log_type TEXT NOT NULL,
    banner_kind TEXT NOT NULL,
    target_id INTEGER,
    moderator_id INTEGER,
    title TEXT,
    description TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_guild_target_created
ON logs(guild_id, target_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_guild_created
ON logs(guild_id, created_at DESC);
"""

# Pas de schéma log_config ici : cette table appartient à database/db.py. Une seconde
# définition (sans colonne updated_at) entrait en concurrence avec la définition
# canonique selon qui créait la table en premier.


def log_runtime_capabilities() -> None:
    global _RUNTIME_CHECKED
    if _RUNTIME_CHECKED:
        return
    _RUNTIME_CHECKED = True
    # Diagnostics d'environnement : utiles, mais ce ne sont pas des problèmes.
    # Les émettre en WARNING ajoutait dix fausses alertes à chaque démarrage.
    logger.info("RAILWAY GIT SHA = %s", os.getenv("RAILWAY_GIT_COMMIT_SHA") or "?")
    logger.info("DISCORD.PY RUNTIME VERSION = %s", getattr(discord, "__version__", "?"))
    for name in ("LayoutView", "Container", "MediaGallery", "Section", "TextDisplay", "Thumbnail", "Separator", "ActionRow"):
        logger.debug("discord.ui.%-14s = %s", name, hasattr(discord.ui, name))


def safe_text(value: object) -> str:
    text = str(value or "").strip()
    return _MENTION_RE.sub(lambda match: "@\u200b" + match.group(1), text)


def _clean_lines(value: object) -> str:
    lines: list[str] = []
    for raw in str(value or "").replace("\r", "").splitlines():
        stripped = raw.strip()
        if stripped and _DECORATIVE_LINE_RE.fullmatch(stripped):
            continue
        lines.append(raw.rstrip())
    return "\n".join(lines).strip()


def _field_map(embed: discord.Embed) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for field in embed.fields:
        name = safe_text(field.name)
        value = _clean_lines(safe_text(field.value))
        if name and value:
            if name.casefold().strip(" :") in {"salon", "channel"}:
                mention = _CHANNEL_MENTION_RE.search(value)
                if mention:
                    value = mention.group(0)
            result.append((name, value))
    return result


def _field_value(embed: discord.Embed, *tokens: str) -> str:
    wanted = tuple(token.casefold() for token in tokens)
    for name, value in _field_map(embed):
        low = name.casefold()
        if any(token in low for token in wanted):
            return value
    return ""


def _first_snowflake(value: object) -> int | None:
    match = _SNOWFLAKE_RE.search(str(value or ""))
    return int(match.group(1)) if match else None


def _first_user_ref(value: object) -> str:
    match = _USER_MENTION_RE.search(str(value or ""))
    if match:
        return match.group(0)
    sid = _first_snowflake(value)
    return f"<@{sid}>" if sid else ""


def _first_role_ref(value: object) -> str:
    match = _ROLE_MENTION_RE.search(str(value or ""))
    if match:
        return match.group(0)
    sid = _first_snowflake(value)
    return f"<@&{sid}>" if sid else ""


def _first_channel_ref(value: object) -> str:
    match = _CHANNEL_MENTION_RE.search(str(value or ""))
    if match:
        return match.group(0)
    sid = _first_snowflake(value)
    return f"<#{sid}>" if sid else ""


def _code_block(value: object) -> str:
    text = _clean_lines(value) or "Contenu vide"
    text = text.replace("```", "`\u200b``")
    return f"```\n{text[:1600]}\n```"


def _strip_identity_prelude(description: str, identity_name: str | None, identity_id: int | None) -> str:
    if not description:
        return ""
    lines = description.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if identity_name and lines:
        first = re.sub(r"[*_`#>]", "", lines[0]).strip().casefold()
        if identity_name.casefold() in first:
            lines.pop(0)
    if identity_id and lines and str(identity_id) in lines[0]:
        lines.pop(0)
    while lines and not lines[0].strip():
        lines.pop(0)
    return _clean_lines("\n".join(lines))


def _display_entity_from_guild(
    guild: discord.Guild | None,
    category: str,
    entity_id: int | None,
) -> tuple[str | None, str | None]:
    if guild is None or not entity_id:
        return None, None
    try:
        if category in {"moderation", "members", "voice", "protection", "tickets"}:
            member = guild.get_member(entity_id)
            if member is not None:
                return member.display_name, str(member.display_avatar.url)
        if category == "roles":
            role = guild.get_role(entity_id)
            if role is not None:
                return role.name, None
        if category in {"channels", "server"}:
            channel = guild.get_channel(entity_id)
            if channel is not None:
                return getattr(channel, "name", str(channel)), None
    except Exception:
        logger.exception("SENTRIX V2 identity guild lookup failed")
    return None, None


def derive_identity(
    embed: discord.Embed,
    *,
    log_type: str,
    guild: discord.Guild | None = None,
    identity_name: str | None = None,
    identity_id: int | None = None,
    identity_icon: str | None = None,
) -> tuple[str | None, int | None, str | None]:
    category, _emoji, _kind = resolve(log_type, embed.title or "", embed.description or "")

    if identity_id is None:
        for label in _TARGET_LABELS:
            value = _field_value(embed, label)
            identity_id = _first_snowflake(value)
            if identity_id:
                break
    if identity_id is None:
        identity_id = _first_snowflake(embed.description)

    looked_name, looked_icon = _display_entity_from_guild(guild, category, identity_id)
    if not identity_name:
        identity_name = looked_name
    if not identity_icon:
        identity_icon = looked_icon

    if not identity_name:
        author_name = safe_text(getattr(embed.author, "name", None))
        if author_name and author_name.casefold() not in {"sentrix", "journal sentrix"}:
            identity_name = author_name
    if not identity_icon:
        identity_icon = str(getattr(embed.author, "icon_url", None) or "") or None

    description = _clean_lines(embed.description)
    if not identity_name and description:
        first = description.splitlines()[0].strip()
        bold = re.match(r"\*\*(.+?)\*\*", first)
        if bold:
            identity_name = safe_text(bold.group(1))[:80]

    if not identity_name:
        for label in _TARGET_LABELS:
            value = _field_value(embed, label)
            if not value:
                continue
            mention = _first_user_ref(value) or _first_role_ref(value) or _first_channel_ref(value)
            identity_name = mention or value.splitlines()[0].strip("*` ")[:80]
            if identity_name:
                break

    if not identity_icon:
        thumb = getattr(embed.thumbnail, "url", None)
        identity_icon = str(thumb) if thumb else None

    return identity_name, identity_id, identity_icon


def compact_fields(embed: discord.Embed, *, limit: int = 2200) -> str:
    """Compatibilité : ne conserve que les détails longs, jamais une ligne de métadonnées plate."""
    blocks: list[str] = []
    ignored = {"auteur", "author", "salon", "channel", "membre", "member", "modérateur", "moderateur", "staff", "rôle", "role"}
    for name, value in _field_map(embed):
        low = name.casefold().strip(" :")
        if any(token == low for token in ignored):
            continue
        if low in {"contenu", "content", "avant", "après", "apres"}:
            blocks.append(f"**{name}**\n{_code_block(value)}")
        elif len(value) > 70 or "\n" in value or low in {"raison", "reason", "changements", "changes", "participants"}:
            blocks.append(f"**{name} :** {value}")
    text = "\n\n".join(blocks)
    return text[:limit]


def _with_id(mention: str) -> str:
    """Mention suivie de son ID en inline code, comme demandé par le format narratif."""
    if not mention:
        return ""
    snowflake = _first_snowflake(mention)
    return f"{mention} (`{snowflake}`)" if snowflake else mention


def narrative_body(
    embed: discord.Embed,
    *,
    log_type: str,
    identity_name: str | None = None,
    identity_id: int | None = None,
) -> str:
    """Construit le bloc événement narratif et les éventuels détails longs."""
    event_type = canonical_event_type(log_type, embed.title or "", embed.description or "")
    member = _first_user_ref(_field_value(embed, "membre", "auteur", "utilisateur", "cible"))
    if not member and identity_id:
        member = f"<@{identity_id}>"
    moderator = _with_id(
        _first_user_ref(
            _field_value(embed, "modérateur", "moderateur", "staff", "responsable", "acteur", "créateur")
        )
    )
    channel = _first_channel_ref(_field_value(embed, "salon", "channel"))
    role = _first_role_ref(_field_value(embed, "rôle", "role"))
    reason = _field_value(embed, "raison", "reason")
    content = _field_value(embed, "contenu", "content")
    before = _field_value(embed, "avant", "before")
    after = _field_value(embed, "après", "apres", "after")
    account_created = _field_value(embed, "compte créé", "compte cree", "account created")
    duration = _field_value(embed, "durée", "duree", "présence", "presence")

    lines: list[str] = []
    if event_type == "message_delete":
        lines.append(f"Un message de {member or 'un membre'} a été supprimé" + (f" dans {channel}" if channel else "") + ".")
        if content:
            lines.append(_code_block(content))
    elif event_type == "message_edit":
        lines.append(f"{member or 'Un membre'} a modifié un message" + (f" dans {channel}" if channel else "") + ".")
        if before:
            lines.append(f"**Avant**\n{_code_block(before)}")
        if after:
            lines.append(f"**Après**\n{_code_block(after)}")
    elif event_type == "message_bulk":
        lines.append((embed.description or "Plusieurs messages ont été supprimés.").strip())
    elif event_type == "member_join":
        lines.append(f"{member or 'Un membre'} vient de rejoindre le serveur.")
        if account_created:
            lines.append(f"Son compte a été créé le **{account_created}**.")
    elif event_type == "member_leave":
        lines.append(f"{member or 'Un membre'} a quitté le serveur.")
        if duration:
            lines.append(f"Présence sur le serveur : **{duration}**.")
    elif event_type == "member_kick":
        lines.append(f"{member or 'Un membre'} a été expulsé" + (f" par {moderator}" if moderator else "") + ".")
        if reason:
            lines.append(f"**Raison :** {reason}")
    elif event_type == "member_ban":
        lines.append(f"{member or 'Un membre'} a été banni" + (f" par {moderator}" if moderator else "") + ".")
        if reason:
            lines.append(f"**Raison :** {reason}")
    elif event_type == "member_unban":
        lines.append(f"{member or 'Un membre'} a été débanni" + (f" par {moderator}" if moderator else "") + ".")
        if reason:
            lines.append(f"**Raison :** {reason}")
    elif event_type == "member_timeout":
        sentence = f"{member or 'Un membre'} a été mis en timeout"
        if moderator:
            sentence += f" par {moderator}"
        if duration:
            sentence += f" pour **{duration}**"
        lines.append(sentence + ".")
        if reason:
            lines.append(f"**Raison :** {reason}")
    elif event_type == "member_untimeout":
        lines.append(f"Le timeout de {member or 'ce membre'} a été retiré" + (f" par {moderator}" if moderator else "") + ".")
    elif event_type == "member_warn":
        lines.append(f"{member or 'Un membre'} a reçu un avertissement" + (f" de {moderator}" if moderator else "") + ".")
        if reason:
            lines.append(f"**Raison :** {reason}")
    elif event_type in {"role_add", "role_remove"}:
        # Ces logs n'avaient AUCUNE branche narrative : le corps restait
        # entièrement vide, y compris le membre concerné. Le salon de logs
        # bloque déjà toute notification (allowed_mentions=NO_PINGS à
        # l'envoi) : la mention identifie le membre sans jamais le notifier.
        verb = "reçu" if event_type == "role_add" else "perdu"
        lines.append(
            f"{member or 'Un membre'} a {verb} le rôle {role or 'un rôle'}"
            + (f", par {moderator}" if moderator else "")
            + "."
        )
    elif event_type in {"channel_create", "channel_delete", "channel_update"}:
        verb = {"channel_create": "créé", "channel_delete": "supprimé", "channel_update": "modifié"}[event_type]
        entity = identity_name or channel or "Un salon"
        id_part = f" (`{identity_id}`)" if identity_id else ""
        lines.append(f"Le salon **{entity}**{id_part} a été {verb}" + (f" par {moderator}" if moderator else "") + ".")
    elif event_type in {"role_create", "role_delete", "role_update"}:
        verb = {"role_create": "créé", "role_delete": "supprimé", "role_update": "modifié"}[event_type]
        # Un mention de rôle (<@&id>) reste toujours cliquable et lisible ; un
        # nom de rôle brut peut contenir des astérisques ou autres caractères
        # qui cassent le markdown quand ils sont eux-mêmes mis en gras.
        entity = role or (f"**{identity_name}**" if identity_name else None) or "Un rôle"
        lines.append(f"Le rôle {entity} a été {verb}" + (f" par {moderator}" if moderator else "") + ".")
        if event_type == "role_update":
            # compact_fields() ignore les valeurs courtes (<70 caractères, pas
            # de saut de ligne) : « Nom » et « Couleur » ne passaient donc
            # jamais, et « Rôle modifié » ne disait jamais CE QUI avait changé.
            nom = _field_value(embed, "nom")
            if nom:
                lines.append(f"**Nom :** {nom}")
            couleur = _field_value(embed, "couleur")
            if couleur:
                lines.append(f"**Couleur :** {couleur}")
            position = _field_value(embed, "position modifiée", "position")
            if position:
                lines.append(f"**Position :** {position}")
            permissions_ajoutees = _field_value(embed, "permissions ajoutées")
            if permissions_ajoutees:
                lines.append(f"**Permissions ajoutées :** {permissions_ajoutees}")
            permissions_supprimees = _field_value(embed, "permissions supprimées")
            if permissions_supprimees:
                lines.append(f"**Permissions retirées :** {permissions_supprimees}")
    elif event_type == "member_update":
        # Seuls les changements de surnom passent par cette branche
        # aujourd'hui (cogs/logs.py). Avant/Après ne sont PAS ajoutés ici :
        # compact_fields() (plus bas) les rend déjà, dans le même style que
        # message_edit — les dupliquer ici les aurait affichés deux fois,
        # sous deux formats différents.
        if before and after:
            lines.append(f"{member or 'Un membre'} a changé de surnom" + (f", par {moderator}" if moderator else "") + ".")
        else:
            lines.append(f"{member or 'Un membre'} a été modifié" + (f" par {moderator}" if moderator else "") + ".")
    elif event_type in {"invite_create", "invite_delete"}:
        verb = "créée" if event_type == "invite_create" else "supprimée"
        lines.append(
            f"Une invitation a été {verb}" + (f" par {moderator}" if moderator else "")
            + (f" pour {channel}" if channel else "") + "."
        )
        lien = _field_value(embed, "lien")
        if lien:
            lines.append(f"**Lien :** {lien}")
        code = _field_value(embed, "code")
        if code:
            lines.append(f"**Code :** {code}")
        expire = _field_value(embed, "expire")
        if expire:
            lines.append(f"**Expire :** {expire}")
        utilisations = _field_value(embed, "utilisations max")
        if utilisations:
            lines.append(f"**Utilisations max :** {utilisations}")
    elif event_type == "guild_update":
        lines.append(f"Les paramètres du serveur ont été modifiés" + (f" par {moderator}" if moderator else "") + ".")
        for label, affichage in (
            ("nom", "Nom"), ("niveau de vérification", "Niveau de vérification"),
            ("délai afk", "Délai AFK"),
        ):
            valeur = _field_value(embed, label)
            if valeur:
                lines.append(f"**{affichage} :** {valeur}")
    elif event_type == "voice_join":
        lines.append(f"{member or 'Un membre'} a rejoint {channel or 'un salon vocal'}.")
    elif event_type == "voice_leave":
        lines.append(f"{member or 'Un membre'} a quitté {channel or 'un salon vocal'}" + (f", après **{duration}**" if duration else "") + ".")
    elif event_type == "voice_move":
        lines.append(_strip_identity_prelude(_clean_lines(embed.description), identity_name, identity_id) or f"{member or 'Un membre'} a été déplacé en vocal.")
    elif event_type == "ticket_close":
        lines.append(_strip_identity_prelude(_clean_lines(embed.description), identity_name, identity_id) or "Le ticket a été fermé.")
    elif event_type.startswith("automod_") or event_type == "antiraid":
        base = _strip_identity_prelude(_clean_lines(embed.description), identity_name, identity_id)
        lines.append(base or f"Une protection SentriX s'est déclenchée pour {member or 'un membre'}.")
        if reason:
            lines.append(f"**Raison :** {reason}")
    else:
        base = _strip_identity_prelude(_clean_lines(embed.description), identity_name, identity_id)
        if base:
            lines.append(base)

    # Ajoute uniquement les blocs longs qui n'ont pas déjà été rendus. La comparaison
    # porte sur le CORPS du bloc, pas sur le bloc entier : "**Contenu**\n```texte```"
    # et "```texte```" désignent la même information, et le contenu d'un message
    # supprimé sortait donc deux fois.
    extras = compact_fields(embed, limit=1800)
    if extras:
        existing = "\n\n".join(lines)
        for block in extras.split("\n\n"):
            if not block.strip():
                continue
            body = block.split("\n", 1)[1] if block.startswith("**") and "\n" in block else block
            if body.strip() and body.strip() in existing:
                continue
            if block in existing:
                continue
            lines.append(block)

    return "\n\n".join(part for part in lines if part.strip())[:3000]


def _clone_button(item: discord.ui.Button) -> discord.ui.Button | None:
    try:
        kwargs: dict[str, Any] = {
            "label": item.label,
            "style": item.style,
            "emoji": item.emoji,
            "disabled": item.disabled,
        }
        if item.style is discord.ButtonStyle.link:
            kwargs["url"] = item.url
        elif getattr(item, "sku_id", None):
            kwargs["sku_id"] = item.sku_id
        else:
            kwargs["custom_id"] = item.custom_id
        button = discord.ui.Button(**kwargs)
        if item.style is not discord.ButtonStyle.link and not getattr(item, "sku_id", None):
            button.callback = item.callback
        return button
    except Exception:
        logger.exception("SENTRIX V2 clone_button failed")
        return None


def build_rows(old_view: discord.ui.View | None) -> list[discord.ui.ActionRow]:
    if old_view is None:
        return []
    buttons: list[discord.ui.Button] = []
    for item in old_view.children:
        if not isinstance(item, discord.ui.Button):
            continue
        button = _clone_button(item)
        if button is None:
            continue
        if button.style is not discord.ButtonStyle.link and not getattr(button, "sku_id", None):
            button.style = discord.ButtonStyle.secondary
        buttons.append(button)
    rows: list[discord.ui.ActionRow] = []
    for start in range(0, len(buttons), 5):
        try:
            rows.append(discord.ui.ActionRow(*buttons[start:start + 5]))
        except Exception:
            logger.exception("SENTRIX V2 action row failed")
    return rows


def _sep() -> discord.ui.Separator:
    spacing_enum = getattr(discord, "SeparatorSpacing", None)
    small = getattr(spacing_enum, "small", None) if spacing_enum is not None else None
    if small is not None:
        try:
            return discord.ui.Separator(spacing=small)
        except (TypeError, ValueError):
            pass
    return discord.ui.Separator()


def _accent_for_kind(kind: str) -> int | None:
    pair = COLORS.get(kind)
    if not pair:
        return None
    r, g, b = pair[0]
    return (r << 16) | (g << 8) | b


class WideLogView(discord.ui.LayoutView):
    def __init__(
        self,
        embed: discord.Embed,
        banner_filename: str,
        old_view: discord.ui.View | None = None,
        accent: int | None = None,
        identity_name: str | None = None,
        identity_id: int | None = None,
        identity_icon: str | None = None,
        emoji: str = "",
        log_type: str = "",
    ) -> None:
        super().__init__(timeout=None)
        container = discord.ui.Container(
            accent_colour=discord.Colour(accent) if accent is not None else None
        )

        # Deux séparateurs maximum par panneau. Le compteur garantit la règle quelle que
        # soit la combinaison de blocs présents (identité absente, boutons absents...).
        separators = 0

        def add_separator() -> bool:
            nonlocal separators
            if separators >= 2:
                return False
            try:
                container.add_item(_sep())
            except Exception:
                logger.exception("SENTRIX V2 separator")
                return False
            separators += 1
            return True

        # add_item(media=...) sans description= : une description affiche un badge « ALT »
        # par-dessus la bannière.
        gallery = discord.ui.MediaGallery()
        gallery.add_item(media=f"attachment://{banner_filename}")
        container.add_item(gallery)
        add_separator()

        # BLOC 1 — identité de l'entité concernée, jamais le bot par défaut.
        if identity_name:
            ident = f"## {safe_text(identity_name)[:80]}"
            if identity_id:
                ident += f"\n> -# ID : {identity_id}"
            placed = False
            if identity_icon:
                try:
                    container.add_item(
                        discord.ui.Section(
                            discord.ui.TextDisplay(ident),
                            # Thumbnail sans description= : sinon Discord affiche « ALT ».
                        accessory=discord.ui.Thumbnail(str(identity_icon)),
                        )
                    )
                    placed = True
                except Exception:
                    logger.exception("SENTRIX V2 identity section")
            if not placed:
                container.add_item(discord.ui.TextDisplay(ident))
            add_separator()

        # BLOC 2 — événement.
        title = safe_text(embed.title or "Journal SentriX")[:200]
        badge = emoji or EVENT_EMOJI.get(log_type, DEFAULT_EVENT_EMOJI)
        heading = f"### {badge} {title}".strip()
        container.add_item(discord.ui.TextDisplay(heading))

        body = narrative_body(
            embed,
            log_type=log_type,
            identity_name=identity_name,
            identity_id=identity_id,
        )
        if body:
            container.add_item(discord.ui.TextDisplay(body[:3000]))

        footer = safe_text(getattr(embed.footer, "text", None))[:250]
        if footer:
            container.add_item(discord.ui.TextDisplay(f"-# {footer}"))

        # Les boutons restent DANS le Container, en ActionRow, tous en secondary.
        rows = build_rows(old_view)
        if rows:
            add_separator()
            for row in rows:
                container.add_item(row)

        self.add_item(container)


def _database_path() -> str:
    return str(config.DATABASE_PATH)


def _ensure_database_parent() -> None:
    path = _database_path()
    if path == ":memory:" or path.startswith("file:"):
        return
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


async def ensure_log_storage(force: bool = False) -> None:
    global _DB_READY
    if _DB_READY and not force:
        return
    _ensure_database_parent()
    async with aiosqlite.connect(_database_path()) as db:
        await db.execute("PRAGMA busy_timeout = 5000")
        # Uniquement la table d'historique des logs. Le routage (log_config) est créé et
        # migré par database/db.py sur la connexion principale du bot.
        await db.executescript(_LOG_SCHEMA)
        await db.commit()
    _DB_READY = True


def _field_id(embed: discord.Embed, labels: tuple[str, ...]) -> int | None:
    for field in embed.fields:
        name = str(field.name or "").casefold()
        if any(label in name for label in labels):
            sid = _first_snowflake(field.value)
            if sid is not None:
                return sid
    return None


def extract_history_ids(embed: discord.Embed) -> tuple[int | None, int | None]:
    target_id = _field_id(embed, _TARGET_LABELS)
    moderator_id = _field_id(embed, _MODERATOR_LABELS)
    if target_id is None:
        target_id = _first_snowflake(embed.description)
    return target_id, moderator_id


def _history_description(embed: discord.Embed) -> str:
    parts: list[str] = []
    if embed.description:
        parts.append(safe_text(embed.description))
    for name, value in _field_map(embed):
        parts.append(f"{name}: {value}")
        if len("\n".join(parts)) >= 1800:
            break
    return "\n".join(parts)[:1800]


async def _record_log(*, guild_id: int, log_type: str, kind: str, embed: discord.Embed) -> None:
    await ensure_log_storage()
    target_id, moderator_id = extract_history_ids(embed)
    async with aiosqlite.connect(_database_path()) as db:
        await db.execute("PRAGMA busy_timeout = 5000")
        await db.execute(
            "INSERT INTO logs (guild_id,log_type,banner_kind,target_id,moderator_id,title,description,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (int(guild_id), str(log_type), str(kind), target_id, moderator_id, safe_text(embed.title)[:300], _history_description(embed), int(time.time())),
        )
        await db.commit()


async def _record_log_safe(**kwargs: Any) -> None:
    try:
        await _record_log(**kwargs)
    except Exception:
        logger.exception("Historique SQLite du log ignoré après échec")


def _schedule_history(channel: discord.abc.Messageable, embed: discord.Embed, log_type: str, kind: str) -> None:
    guild_id = getattr(getattr(channel, "guild", None), "id", None)
    if guild_id is None:
        return
    try:
        asyncio.create_task(_record_log_safe(guild_id=int(guild_id), log_type=log_type, kind=kind, embed=embed.copy()))
    except RuntimeError:
        logger.debug("Aucune boucle asyncio active pour l'historique des logs.")


def _rewind_file(file: discord.File | None) -> None:
    if file is None:
        return
    try:
        file.fp.seek(0)
    except Exception:
        pass


async def send_wide_log(
    channel: discord.abc.Messageable,
    embed: discord.Embed,
    *,
    log_type: str,
    old_view: discord.ui.View | None = None,
    extra_file: discord.File | None = None,
    identity_name: str | None = None,
    identity_id: int | None = None,
    identity_icon: str | None = None,
) -> bool:
    """Envoie le log Components V2 avec bannière, identité, événement et actions."""
    log_runtime_capabilities()
    event_type = canonical_event_type(log_type, embed.title or "", embed.description or "")
    _category, emoji, kind = resolve(event_type, embed.title or "", embed.description or "")
    banner_path = get_banner(event_type, embed.title or "", embed.description or "")
    banner_filename = f"sentrix_log_{kind}.png"

    logger.debug(
        "SXTRACE 6 TRANSPORT phase=enter channel=%s log_type=%s event_type=%s kind=%s "
        "banner=%s banner_exists=%s",
        getattr(channel, "id", "?"), log_type, event_type, kind,
        banner_path, banner_path.exists(),
    )

    if not banner_path.exists():
        logger.error(
            "SXTRACE 6 TRANSPORT phase=abort reason=BANNER_MISSING path=%s", banner_path
        )
        logger.error("SENTRIX LOG V2 FAILED bannière introuvable: %s", banner_path)
        return False

    guild = getattr(channel, "guild", None)
    identity_name, identity_id, identity_icon = derive_identity(
        embed,
        log_type=event_type,
        guild=guild if isinstance(guild, discord.Guild) else None,
        identity_name=identity_name,
        identity_id=identity_id,
        identity_icon=identity_icon,
    )

    try:
        view = WideLogView(
            embed,
            banner_filename,
            old_view,
            _accent_for_kind(kind),
            identity_name,
            identity_id,
            identity_icon,
            emoji,
            event_type,
        )
    except Exception as exc:
        logger.error(
            "SXTRACE 6 TRANSPORT phase=abort reason=VIEW_BUILD_FAILED type=%s",
            type(exc).__name__,
        )
        logger.error("SENTRIX LOG V2 FAILED construction type=%s message=%s\n%s", type(exc).__name__, exc, traceback.format_exc())
        return False

    try:
        banner_file = discord.File(str(banner_path), filename=banner_filename)
    except Exception as exc:
        logger.error(
            "SXTRACE 6 TRANSPORT phase=abort reason=BANNER_FILE_FAILED type=%s",
            type(exc).__name__,
        )
        logger.error("SENTRIX LOG V2 FAILED file type=%s message=%s\n%s", type(exc).__name__, exc, traceback.format_exc())
        return False

    files: list[discord.File] = [banner_file]
    if extra_file is not None:
        _rewind_file(extra_file)
        files.append(extra_file)

    logger.debug(
        "SXTRACE 6 TRANSPORT phase=before-send channel=%s event_type=%s files=%s view=%s",
        getattr(channel, "id", "?"), event_type, len(files), type(view).__name__,
    )
    try:
        message = await channel.send(view=view, files=files, allowed_mentions=NO_PINGS)
        logger.debug(
            "SXTRACE 6 TRANSPORT phase=after-send channel=%s event_type=%s message_id=%s",
            getattr(channel, "id", "?"), event_type, getattr(message, "id", "?"),
        )
        flags_value = int(getattr(getattr(message, "flags", None), "value", 0) or 0)
        logger.debug(
            "SENTRIX LOG V2 SUCCESS message_id=%s type=%s kind=%s components_v2=%s",
            getattr(message, "id", "?"), event_type, kind, bool(flags_value & 32768),
        )
        _schedule_history(channel, embed, event_type, kind)
        return True
    except discord.HTTPException as exc:
        logger.error(
            "SXTRACE 6 TRANSPORT phase=send-failed channel=%s reason=HTTP status=%s code=%s",
            getattr(channel, "id", "?"), getattr(exc, "status", None), getattr(exc, "code", None),
        )
        logger.error("SENTRIX LOG V2 FAILED HTTP status=%s code=%s text=%r\n%s", getattr(exc, "status", None), getattr(exc, "code", None), getattr(exc, "text", None), traceback.format_exc())
    except Exception as exc:
        logger.error(
            "SXTRACE 6 TRANSPORT phase=send-failed channel=%s reason=%s",
            getattr(channel, "id", "?"), type(exc).__name__,
        )
        logger.error("SENTRIX LOG V2 FAILED type=%s message=%s\n%s", type(exc).__name__, exc, traceback.format_exc())
    return False


# upsert_log_config SUPPRIMÉ : il écrivait le routage sur une connexion aiosqlite
# distincte de bot.db, avec un schéma sans updated_at. Le seul point d'écriture est
# désormais log_service.set_log_config.


async def fetch_log_history(guild_id: int, target_id: int, limit: int = 10) -> list[dict[str, Any]]:
    await ensure_log_storage()
    safe_limit = max(1, min(int(limit), 50))
    async with aiosqlite.connect(_database_path()) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA busy_timeout = 5000")
        cursor = await db.execute(
            "SELECT id,guild_id,log_type,banner_kind,target_id,moderator_id,title,description,created_at "
            "FROM logs WHERE guild_id=? AND target_id=? ORDER BY created_at DESC,id DESC LIMIT ?",
            (int(guild_id), int(target_id), safe_limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
    return [dict(row) for row in rows]


__all__ = [
    "FALLBACK_ENABLED", "NO_PINGS", "WideLogView", "build_rows", "compact_fields",
    "derive_identity", "ensure_log_storage", "extract_history_ids", "fetch_log_history",
    "log_runtime_capabilities", "narrative_body", "safe_text", "send_wide_log",
]
