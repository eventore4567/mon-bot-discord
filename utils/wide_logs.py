"""Renderer Components V2 et historique SQLite des journaux SentriX.

Le message Components V2 contient toujours la bannière 1024 px comme premier composant.
La persistance SQLite est volontairement secondaire : un échec de base de données ne doit
jamais empêcher Discord de recevoir le journal.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any

import aiosqlite
import discord

import config
from utils.log_banners import banner_kind, get_banner

logger = logging.getLogger("bot.wide-logs")

NO_PINGS = discord.AllowedMentions(
    everyone=False,
    users=False,
    roles=False,
    replied_user=False,
)

# Braille blanc : visuellement neutre, mais conserve une largeur utile au conteneur.
WIDE_FILLER = "\u2800" * 70

_MENTION_RE = re.compile(r"@(everyone|here)\b", re.IGNORECASE)
_SNOWFLAKE_RE = re.compile(r"(?<!\d)(\d{15,22})(?!\d)")
_DB_READY = False

_TARGET_LABELS = (
    "auteur", "author", "cible", "target", "membre", "member",
    "utilisateur", "user", "victime",
)
_MODERATOR_LABELS = (
    "modérateur", "moderateur", "moderator", "staff", "exécuteur",
    "executeur", "executor", "acteur", "actor", "responsable",
)

_SCHEMA = """
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

CREATE TABLE IF NOT EXISTS log_config (
    guild_id INTEGER NOT NULL,
    log_type TEXT NOT NULL,
    channel_id INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(guild_id, log_type)
);
"""


def safe_text(value: object) -> str:
    """Neutralise @everyone/@here tout en gardant les mentions ID lisibles."""
    text = str(value or "").strip()
    return _MENTION_RE.sub(lambda match: "@\u200b" + match.group(1), text)


def compact_fields(embed: discord.Embed) -> str:
    """Regroupe les petits champs sur une même ligne pour garder le log horizontal."""
    blocks: list[str] = []
    small: list[str] = []

    def flush() -> None:
        nonlocal small
        if small:
            blocks.append("\u3000•\u3000".join(small))
            small = []

    for field in embed.fields:
        name = safe_text(field.name)
        value = safe_text(field.value)

        if not name or not value:
            continue

        if len(value) <= 90 and "\n" not in value and len(name) <= 35:
            small.append(f"**{name} :** {value}")
            if len(small) == 3:
                flush()
            continue

        flush()
        blocks.append(f"**{name}**\n{value}")

    flush()

    result = "\n\n".join(blocks)
    return result[:3797] + "..." if len(result) > 3800 else result


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
        logger.debug("Impossible de recopier un bouton de log legacy.", exc_info=True)
        return None


def copy_buttons(container: discord.ui.Container, old_view: discord.ui.View | None) -> None:
    """Recopie les boutons de l'ancienne vue dans le conteneur Components V2."""
    if old_view is None:
        return

    buttons: list[discord.ui.Button] = []
    for item in old_view.children:
        if not isinstance(item, discord.ui.Button):
            continue
        button = _clone_button(item)
        if button is not None:
            buttons.append(button)

    if not buttons:
        return

    container.add_item(discord.ui.Separator())
    for start in range(0, len(buttons), 5):
        container.add_item(discord.ui.ActionRow(*buttons[start:start + 5]))


class WideLogView(discord.ui.LayoutView):
    """Panneau de log SentriX : bannière, contenu compact puis actions."""

    def __init__(
        self,
        embed: discord.Embed,
        banner_filename: str,
        old_view: discord.ui.View | None = None,
        accent: int | None = None,
    ) -> None:
        # timeout=None évite que les boutons meurent au bout de cinq minutes tant que
        # le processus reste actif. La persistance après redémarrage reste gérée par
        # l'enregistrement des vues persistantes de discord.py, pas par ce timeout seul.
        super().__init__(timeout=None)

        accent_colour = discord.Colour(accent) if accent is not None else None
        container = discord.ui.Container(accent_colour=accent_colour)

        # 1. La bannière est volontairement le PREMIER composant du conteneur.
        gallery = discord.ui.MediaGallery()
        gallery.add_item(
            media=f"attachment://{banner_filename}",
            description="SentriX Logs",
        )
        container.add_item(gallery)

        # 2. Titre et miniature.
        title = safe_text(embed.title or "Journal SentriX")
        thumbnail = getattr(embed.thumbnail, "url", None)

        if thumbnail:
            container.add_item(
                discord.ui.Section(
                    discord.ui.TextDisplay(f"## {title}"),
                    accessory=discord.ui.Thumbnail(
                        str(thumbnail),
                        description="SentriX",
                    ),
                )
            )
        else:
            container.add_item(discord.ui.TextDisplay(f"## {title}"))

        # 3. Description.
        description = safe_text(embed.description)
        if description:
            container.add_item(discord.ui.TextDisplay(description[:1500]))

        # 4. Champs compactés.
        fields = compact_fields(embed)
        if fields:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(fields))

        # 5. Largeur constante, même pour un log très court.
        container.add_item(discord.ui.TextDisplay(WIDE_FILLER))

        # 6. Footer.
        footer = getattr(embed.footer, "text", None)
        if footer:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(f"-# {safe_text(footer)[:500]}"))

        # 7. Boutons existants : copier ID, voir le message, etc.
        copy_buttons(container, old_view)
        self.add_item(container)


def _database_path() -> str:
    return str(config.DATABASE_PATH)


def _ensure_database_parent() -> None:
    path = _database_path()
    if path == ":memory:" or path.startswith("file:"):
        return
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


async def ensure_log_storage(force: bool = False) -> None:
    """Crée les tables d'historique et de miroir de configuration."""
    global _DB_READY
    if _DB_READY and not force:
        return

    _ensure_database_parent()
    async with aiosqlite.connect(_database_path()) as db:
        await db.execute("PRAGMA busy_timeout = 5000")
        await db.executescript(_SCHEMA)
        await db.commit()
    _DB_READY = True


def _first_snowflake(value: object) -> int | None:
    match = _SNOWFLAKE_RE.search(str(value or ""))
    return int(match.group(1)) if match else None


def _field_id(embed: discord.Embed, labels: tuple[str, ...]) -> int | None:
    for field in embed.fields:
        name = str(field.name or "").casefold()
        if any(label in name for label in labels):
            snowflake = _first_snowflake(field.value)
            if snowflake is not None:
                return snowflake
    return None


def extract_history_ids(embed: discord.Embed) -> tuple[int | None, int | None]:
    """Extrait prudemment la cible et le modérateur depuis les champs du log."""
    target_id = _field_id(embed, _TARGET_LABELS)
    moderator_id = _field_id(embed, _MODERATOR_LABELS)
    return target_id, moderator_id


def _history_description(embed: discord.Embed) -> str:
    parts: list[str] = []
    description = safe_text(embed.description)
    if description:
        parts.append(description)
    for field in embed.fields:
        name = safe_text(field.name)
        value = safe_text(field.value)
        if name and value:
            parts.append(f"{name}: {value}")
        if len("\n".join(parts)) >= 1800:
            break
    return "\n".join(parts)[:1800]


async def _record_log(
    *,
    guild_id: int,
    log_type: str,
    kind: str,
    embed: discord.Embed,
) -> None:
    await ensure_log_storage()
    target_id, moderator_id = extract_history_ids(embed)

    async with aiosqlite.connect(_database_path()) as db:
        await db.execute("PRAGMA busy_timeout = 5000")
        await db.execute(
            "INSERT INTO logs "
            "(guild_id, log_type, banner_kind, target_id, moderator_id, title, description, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(guild_id),
                str(log_type),
                str(kind),
                target_id,
                moderator_id,
                safe_text(embed.title)[:300],
                _history_description(embed),
                int(time.time()),
            ),
        )
        await db.commit()


async def _record_log_safe(
    *,
    guild_id: int,
    log_type: str,
    kind: str,
    embed: discord.Embed,
) -> None:
    try:
        await _record_log(
            guild_id=guild_id,
            log_type=log_type,
            kind=kind,
            embed=embed,
        )
    except Exception:
        # L'historique est auxiliaire : ne jamais transformer son échec en échec du log.
        logger.exception(
            "Historique SQLite du log ignoré après échec guild=%s type=%s",
            guild_id,
            log_type,
        )


def _schedule_history(channel: discord.abc.Messageable, embed: discord.Embed, log_type: str, kind: str) -> None:
    guild = getattr(channel, "guild", None)
    guild_id = getattr(guild, "id", None)
    if guild_id is None:
        return
    try:
        asyncio.create_task(
            _record_log_safe(
                guild_id=int(guild_id),
                log_type=log_type,
                kind=kind,
                embed=embed.copy(),
            )
        )
    except RuntimeError:
        logger.debug("Aucune boucle asyncio active pour enregistrer l'historique du log.")


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
) -> bool:
    """Envoie un log Components V2, puis retombe sur l'embed classique si nécessaire."""
    title = embed.title or ""
    description = embed.description or ""

    kind = banner_kind(log_type, title, description)
    banner_path = get_banner(log_type, title, description)
    banner_filename = f"sentrix_log_{kind}.png"

    try:
        banner_file = discord.File(str(banner_path), filename=banner_filename)
    except (OSError, FileNotFoundError):
        # Le fichier peut avoir été supprimé entre get_banner() et discord.File().
        banner_path = get_banner(log_type, title, description)
        banner_file = discord.File(str(banner_path), filename=banner_filename)

    files: list[discord.File] = [banner_file]
    if extra_file is not None:
        files.append(extra_file)

    accent = embed.colour.value if embed.colour else None
    view = WideLogView(embed, banner_filename, old_view, accent)

    try:
        await channel.send(
            view=view,
            files=files,
            allowed_mentions=NO_PINGS,
        )
        _schedule_history(channel, embed, log_type, kind)
        return True

    except (discord.Forbidden, discord.HTTPException, FileNotFoundError, OSError):
        logger.warning(
            "Envoi Components V2 impossible pour le log %s ; fallback embed classique.",
            log_type,
            exc_info=True,
        )

        # Repli classique : notamment si le rôle SentriX n'a pas « Joindre des fichiers ».
        _rewind_file(extra_file)
        kwargs: dict[str, Any] = {
            "embed": embed,
            "allowed_mentions": NO_PINGS,
        }
        if old_view is not None:
            kwargs["view"] = old_view
        if extra_file is not None:
            kwargs["file"] = extra_file

        try:
            await channel.send(**kwargs)
            _schedule_history(channel, embed, log_type, kind)
            return True
        except (discord.Forbidden, discord.HTTPException, OSError):
            logger.exception("Fallback embed du log %s impossible.", log_type)
            return False


async def upsert_log_config(
    guild_id: int,
    log_type: str,
    channel_id: int | None,
    enabled: bool,
) -> None:
    """Miroite une configuration de log dans la table demandée ``log_config``."""
    await ensure_log_storage()
    async with aiosqlite.connect(_database_path()) as db:
        await db.execute("PRAGMA busy_timeout = 5000")
        await db.execute(
            "INSERT INTO log_config (guild_id, log_type, channel_id, enabled) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, log_type) DO UPDATE SET "
            "channel_id = excluded.channel_id, enabled = excluded.enabled",
            (int(guild_id), str(log_type), channel_id, 1 if enabled else 0),
        )
        await db.commit()


async def fetch_log_history(guild_id: int, target_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """Retourne les derniers logs concernant un membre, du plus récent au plus ancien."""
    await ensure_log_storage()
    safe_limit = max(1, min(int(limit), 50))
    async with aiosqlite.connect(_database_path()) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA busy_timeout = 5000")
        cursor = await db.execute(
            "SELECT id, guild_id, log_type, banner_kind, target_id, moderator_id, "
            "title, description, created_at FROM logs "
            "WHERE guild_id = ? AND target_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (int(guild_id), int(target_id), safe_limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
    return [dict(row) for row in rows]


__all__ = [
    "NO_PINGS",
    "WIDE_FILLER",
    "WideLogView",
    "compact_fields",
    "ensure_log_storage",
    "extract_history_ids",
    "fetch_log_history",
    "safe_text",
    "send_wide_log",
    "upsert_log_config",
]
