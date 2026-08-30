"""Renderer Components V2 et historique SQLite des journaux SentriX.

Le message Components V2 contient toujours la bannière 1024 px comme premier composant.
La persistance SQLite est volontairement secondaire : un échec de base de données ne doit
jamais empêcher Discord de recevoir le journal.
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
from utils.log_banners import banner_kind, get_banner

logger = logging.getLogger("bot.wide-logs")

NO_PINGS = discord.AllowedMentions(
    everyone=False,
    users=False,
    roles=False,
    replied_user=False,
)

# Conservé pour compatibilité d'import. Il n'existe plus aucun fallback embed classique.
FALLBACK_ENABLED = False
_RUNTIME_CHECKED = False

_MENTION_RE = re.compile(r"@(everyone|here)\b", re.IGNORECASE)
_SNOWFLAKE_RE = re.compile(r"(?<!\d)(\d{15,22})(?!\d)")
_CHANNEL_MENTION_RE = re.compile(r"<#\d{15,22}>")
_DECORATIVE_LINE_RE = re.compile(r"^[\s━─═—–_\-•·┄┈┉┅┇]{8,}$")
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


def log_runtime_capabilities() -> None:
    """Affiche une seule fois les capacités Components V2 réellement chargées sur Railway."""
    global _RUNTIME_CHECKED
    if _RUNTIME_CHECKED:
        return
    _RUNTIME_CHECKED = True

    logger.warning("RAILWAY GIT SHA = %s", os.getenv("RAILWAY_GIT_COMMIT_SHA") or "?")
    logger.warning("DISCORD.PY RUNTIME VERSION = %s", getattr(discord, "__version__", "?"))
    logger.warning("DISCORD.PY VERSION_INFO = %s", getattr(discord, "version_info", "?"))
    logger.warning("DISCORD.PY FILE = %s", getattr(discord, "__file__", "?"))
    logger.warning(
        "SEND PATCHED = %s | qualname=%s | module=%s",
        discord.TextChannel.send is not discord.abc.Messageable.send,
        getattr(discord.TextChannel.send, "__qualname__", "?"),
        getattr(discord.TextChannel.send, "__module__", "?"),
    )

    for name in (
        "LayoutView",
        "Container",
        "MediaGallery",
        "Section",
        "TextDisplay",
        "Thumbnail",
        "Separator",
        "ActionRow",
    ):
        logger.warning("discord.ui.%-14s = %s", name, hasattr(discord.ui, name))

    logger.warning("discord.MediaGalleryItem = %s", hasattr(discord, "MediaGalleryItem"))
    logger.warning(
        "MessageFlags.components_v2 = %s (bit attendu=32768)",
        hasattr(discord.MessageFlags, "components_v2"),
    )


def safe_text(value: object) -> str:
    """Neutralise @everyone/@here tout en gardant les mentions ID lisibles."""
    text = str(value or "").strip()
    return _MENTION_RE.sub(lambda match: "@\u200b" + match.group(1), text)


def _clean_description(value: object) -> str:
    """Retire les anciennes barres décoratives injectées dans les embeds legacy."""
    lines: list[str] = []
    for raw in str(value or "").replace("\r", "").splitlines():
        stripped = raw.strip()
        if stripped and _DECORATIVE_LINE_RE.fullmatch(stripped):
            continue
        lines.append(raw)
    return "\n".join(lines).strip()


def compact_fields(embed: discord.Embed, *, limit: int = 2200) -> str:
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

        if name.casefold() in {"salon", "channel"}:
            channel_mention = _CHANNEL_MENTION_RE.search(value)
            if channel_mention is not None:
                value = channel_mention.group(0)

        if len(value) <= 90 and "\n" not in value and len(name) <= 35:
            small.append(f"**{name} :** {value}")
            if len(small) == 3:
                flush()
            continue

        flush()
        blocks.append(f"**{name}**\n{value}")

    flush()

    result = "\n\n".join(blocks)
    if len(result) > limit:
        return result[: max(1, limit - 1)].rstrip() + "…"
    return result


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
        logger.exception("SENTRIX V2 PHASE C clone_button=failed")
        return None


def copy_buttons(container: discord.ui.Container, old_view: discord.ui.View | None) -> None:
    """Recopie les boutons sans qu'un bouton invalide puisse annuler tout le panneau."""
    if old_view is None:
        logger.warning("SENTRIX V2 PHASE C buttons=none")
        return

    buttons: list[discord.ui.Button] = []
    for item in old_view.children:
        if not isinstance(item, discord.ui.Button):
            continue
        button = _clone_button(item)
        if button is not None:
            buttons.append(button)

    if not buttons:
        logger.warning("SENTRIX V2 PHASE C buttons=none_after_clone")
        return

    rows: list[discord.ui.ActionRow] = []
    for start in range(0, len(buttons), 5):
        chunk = buttons[start:start + 5]
        try:
            rows.append(discord.ui.ActionRow(*chunk))
        except Exception:
            logger.exception(
                "SENTRIX V2 PHASE C action_row=failed start=%s count=%s",
                start,
                len(chunk),
            )

    if not rows:
        logger.warning("SENTRIX V2 PHASE C buttons=degraded_all_rows_failed")
        return

    try:
        container.add_item(discord.ui.Separator())
        for row in rows:
            container.add_item(row)
        logger.warning("SENTRIX V2 PHASE C buttons=ok rows=%s", len(rows))
    except Exception:
        logger.exception("SENTRIX V2 PHASE C container_add=failed")


class WideLogView(discord.ui.LayoutView):
    """Panneau de log SentriX : bannière, contenu compact puis actions."""

    def __init__(
        self,
        embed: discord.Embed,
        banner_filename: str,
        old_view: discord.ui.View | None = None,
        accent: int | None = None,
    ) -> None:
        super().__init__(timeout=None)

        accent_colour = discord.Colour(accent) if accent is not None else None
        container = discord.ui.Container(accent_colour=accent_colour)

        gallery = discord.ui.MediaGallery()
        gallery.add_item(media=f"attachment://{banner_filename}")
        container.add_item(gallery)
        logger.warning("SENTRIX V2 PHASE A banner=ok filename=%s", banner_filename)

        title = safe_text(embed.title or "Journal SentriX")[:256]
        thumbnail = getattr(embed.thumbnail, "url", None)

        section_ok = False
        if thumbnail:
            try:
                container.add_item(
                    discord.ui.Section(
                        discord.ui.TextDisplay(f"## {title}"),
                        accessory=discord.ui.Thumbnail(str(thumbnail)),
                    )
                )
                section_ok = True
                logger.warning("SENTRIX V2 PHASE B thumbnail=ok")
            except Exception:
                logger.exception("SENTRIX V2 PHASE B thumbnail=failed; title_only=1")

        if not section_ok:
            container.add_item(discord.ui.TextDisplay(f"## {title}"))
            if not thumbnail:
                logger.warning("SENTRIX V2 PHASE B thumbnail=none")

        description = _clean_description(safe_text(embed.description))[:900]
        if description:
            container.add_item(discord.ui.TextDisplay(description))

        fields = compact_fields(embed, limit=2200)
        if fields:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(fields))

        footer = getattr(embed.footer, "text", None)
        if footer:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(f"-# {safe_text(footer)[:300]}"))

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
    """Extrait prudemment la cible et le modérateur depuis le log normalisé."""
    target_id = _field_id(embed, _TARGET_LABELS)
    moderator_id = _field_id(embed, _MODERATOR_LABELS)

    if target_id is None:
        target_id = _first_snowflake(embed.description)

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
    """Envoie le vrai log Components V2 ; aucun échec ne retombe sur un embed classique."""
    log_runtime_capabilities()

    title = embed.title or ""
    description = embed.description or ""
    kind = banner_kind(log_type, title, description)
    banner_path = get_banner(log_type, title, description)
    banner_filename = f"sentrix_log_{kind}.png"

    exists = banner_path.exists()
    try:
        size = banner_path.stat().st_size if exists else -1
    except OSError:
        size = -1

    channel_id = getattr(channel, "id", "?")
    logger.warning(
        "SENTRIX LOG V2 START channel_id=%s log_type=%s kind=%s "
        "banner_path=%s banner_exists=%s banner_size=%s discordpy=%s using_layoutview=%s",
        channel_id,
        log_type,
        kind,
        banner_path,
        exists,
        size,
        getattr(discord, "__version__", "?"),
        hasattr(discord.ui, "LayoutView"),
    )

    if not exists:
        logger.error("SENTRIX LOG V2 FAILED banner introuvable: %s", banner_path)
        return False

    accent = embed.colour.value if embed.colour else None
    try:
        view = WideLogView(embed, banner_filename, old_view, accent)
    except Exception as exc:
        logger.error(
            "SENTRIX LOG V2 FAILED construction view type=%s message=%s\n%s",
            type(exc).__name__,
            exc,
            traceback.format_exc(),
        )
        return False

    try:
        banner_file = discord.File(str(banner_path), filename=banner_filename)
    except Exception as exc:
        logger.error(
            "SENTRIX LOG V2 FAILED création discord.File type=%s message=%s\n%s",
            type(exc).__name__,
            exc,
            traceback.format_exc(),
        )
        return False

    files: list[discord.File] = [banner_file]
    if extra_file is not None:
        _rewind_file(extra_file)
        files.append(extra_file)

    try:
        message = await channel.send(
            view=view,
            files=files,
            allowed_mentions=NO_PINGS,
        )
        flags_value = int(getattr(getattr(message, "flags", None), "value", 0) or 0)
        logger.warning(
            "SENTRIX LOG V2 SUCCESS message_id=%s flags=%s components_v2_bit=%s",
            getattr(message, "id", "?"),
            flags_value,
            bool(flags_value & 32768),
        )
        _schedule_history(channel, embed, log_type, kind)
        return True

    except discord.HTTPException as exc:
        logger.error(
            "SENTRIX LOG V2 FAILED HTTPException type=%s status=%s code=%s text=%r "
            "channel_id=%s\n%s",
            type(exc).__name__,
            getattr(exc, "status", None),
            getattr(exc, "code", None),
            getattr(exc, "text", None),
            channel_id,
            traceback.format_exc(),
        )
    except Exception as exc:
        logger.error(
            "SENTRIX LOG V2 FAILED type=%s message=%s channel_id=%s\n%s",
            type(exc).__name__,
            exc,
            channel_id,
            traceback.format_exc(),
        )

    logger.error("SENTRIX LOG V2 ABORT — aucun fallback embed classique n'existe.")
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
    "FALLBACK_ENABLED",
    "NO_PINGS",
    "WideLogView",
    "compact_fields",
    "ensure_log_storage",
    "extract_history_ids",
    "fetch_log_history",
    "log_runtime_capabilities",
    "safe_text",
    "send_wide_log",
    "upsert_log_config",
]
