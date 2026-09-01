"""Transport canonique des journaux Discord SentriX.

Source de vérité runtime : ``log_config`` uniquement.
Les anciennes tables/colonnes ne servent qu'à restaurer une route manquante et à garder
l'ancien écran +setup compatible pendant la transition. Aucun envoi ne lit sa route dans
``log_settings`` ou ``guild_config``.
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections import OrderedDict
from typing import Any

import discord

from utils.log_categories import (
    CATEGORIES,
    CATEGORY_ORDER as CATEGORY_KEYS,
    LOG_REGISTRY,
    canonical_event_type,
    category_for,
    legacy_to_category,
    resolve,
)
from utils.wide_logs import send_wide_log

logger = logging.getLogger("bot")

_LEGACY_COLUMNS = {
    "moderation": "log_moderation",
    "messages": "log_messages",
    "members": "log_members",
    "channels": "log_server",
    "roles": "log_roles",
    "voice": "log_voice",
    "server": "log_channel",
    "tickets": "ticket_log_channel",
    "automod": "log_automod",
    "spam": None,
    "raid": None,
    "resources": None,
    "files": None,
}

LOG_TYPES: dict[str, dict[str, Any]] = {
    key: {
        "label": label,
        "category": label,
        "legacy_column": _LEGACY_COLUMNS.get(key),
        "emits": True,
    }
    for key, label in CATEGORIES.items()
}
CATEGORY_ORDER = [CATEGORIES[key] for key in CATEGORY_KEYS]

DEFAULT_LOG_SETTING = {
    "enabled": True,
    "channel_id": None,
    "dedicated_channel_id": None,
    "fallback_channel_id": None,
    "include_content": True,
    "include_attachments": True,
    "include_actor": True,
    "include_reason": True,
}
LOG_ALLOWED_MENTIONS = discord.AllowedMentions(
    everyone=False, users=False, roles=False, replied_user=False
)

_DEDUP_TTL = 8.0
_DEDUP_MAX = 4096
_recent_event_keys: OrderedDict[str, float] = OrderedDict()
_SCHEMA_READY: set[int] = set()

# Conservé pour quelques anciens modules qui importent cette constante. Le runtime ne
# s'en sert pas comme source de vérité.
_LEGACY_SETTING_KEYS = {
    "moderation": ("moderation", "log_moderation"),
    "messages": ("messages", "log_messages"),
    "members": ("members", "log_members"),
    "channels": ("channels", "log_channels", "log_server"),
    "roles": ("roles", "log_roles"),
    "voice": ("voice", "log_voice"),
    "server": ("server", "system", "log_channel"),
    "tickets": ("tickets", "log_tickets", "ticket_log_channel"),
    "automod": ("automod", "protection", "log_automod"),
    "spam": ("spam", "log_spam"),
    "raid": ("raid", "log_raid"),
    "resources": ("resources", "dossiers", "log_resources", "log_dossiers"),
    "files": ("files", "log_files"),
}


def is_primary_process() -> bool:
    raw = (os.getenv("SENTRIX_LOG_PRODUCER") or "").strip().casefold()
    return raw not in {"0", "false", "no", "off", "disabled"}


def categories_with_types() -> dict[str, list[str]]:
    return {CATEGORIES[key]: [key] for key in CATEGORY_KEYS}


def _now() -> int:
    return int(time.time())


def make_event_key(
    guild_id: int,
    event_type: str,
    *,
    target_id: int | None = None,
    executor_id: int | None = None,
    audit_log_id: int | None = None,
    message_id: int | None = None,
    discriminator: str | int | None = None,
) -> str:
    return ":".join(
        str(part)
        for part in (
            guild_id,
            event_type,
            target_id or 0,
            executor_id or 0,
            audit_log_id or 0,
            message_id or 0,
            discriminator or "",
        )
    )


def _prune_recent(now: float) -> None:
    while _recent_event_keys:
        first_key, first_at = next(iter(_recent_event_keys.items()))
        if now - first_at <= _DEDUP_TTL and len(_recent_event_keys) <= _DEDUP_MAX:
            break
        _recent_event_keys.pop(first_key, None)


def _is_duplicate(event_key: str | None) -> bool:
    if not event_key:
        return False
    current = time.monotonic()
    _prune_recent(current)
    previous = _recent_event_keys.get(event_key)
    if previous is not None and current - previous <= _DEDUP_TTL:
        return True
    _recent_event_keys[event_key] = current
    _recent_event_keys.move_to_end(event_key)
    return False


def _first_snowflake(text: object) -> int | None:
    match = re.search(r"(?<!\d)(\d{15,22})(?!\d)", str(text or ""))
    return int(match.group(1)) if match else None


def semantic_event_key(guild_id: int, log_type: str, embed: discord.Embed) -> str | None:
    event_type = canonical_event_type(log_type, embed.title or "", embed.description or "")
    if event_type not in {
        "member_ban",
        "member_unban",
        "member_kick",
        "member_timeout",
        "member_untimeout",
        "member_warn",
    }:
        return None
    sample = " ".join(
        [str(embed.title or ""), str(embed.description or "")]
        + [f"{field.name} {field.value}" for field in embed.fields]
    )
    target = _first_snowflake(sample)
    return f"semantic:{guild_id}:{event_type}:{target}" if target else None


class RevealIdButton(discord.ui.Button):
    def __init__(self, label: str, entity_id: int, *, row: int = 0):
        self.entity_id = int(entity_id)
        super().__init__(
            label=label[:80],
            style=discord.ButtonStyle.secondary,
            custom_id=f"sxid:{self.entity_id}",
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"`{self.entity_id}`",
            ephemeral=True,
            allowed_mentions=LOG_ALLOWED_MENTIONS,
        )


class LogActionsView(discord.ui.View):
    def __init__(
        self,
        *,
        jump_url: str | None = None,
        ids: list[tuple[str, int]] | None = None,
    ):
        super().__init__(timeout=None)
        if jump_url:
            self.add_item(
                discord.ui.Button(
                    label="Voir le message",
                    style=discord.ButtonStyle.link,
                    url=jump_url,
                    row=0,
                )
            )
        for label, entity_id in (ids or [])[:4]:
            self.add_item(RevealIdButton(label, entity_id, row=0))


def log_actions(
    *,
    jump_url: str | None = None,
    ids: list[tuple[str, int]] | None = None,
) -> LogActionsView | None:
    return LogActionsView(jump_url=jump_url, ids=ids) if jump_url or ids else None


async def _table_columns(bot, table: str) -> set[str]:
    try:
        rows = await bot.db.fetchall(f"PRAGMA table_info({table})")
    except Exception:
        return set()
    result: set[str] = set()
    for row in rows:
        try:
            result.add(str(row["name"]))
        except (KeyError, IndexError, TypeError):
            try:
                result.add(str(row[1]))
            except Exception:
                pass
    return result


def _legacy_case_sql(prefix: str = "NEW.log_type") -> str:
    """CASE SQLite utilisé uniquement pour synchroniser l'ancien UI vers log_config."""
    pairs: dict[str, str] = {}
    for category, keys in _LEGACY_SETTING_KEYS.items():
        for key in keys:
            pairs[key] = category
    pairs.update({key: key for key in CATEGORIES})
    clauses = " ".join(
        f"WHEN lower({prefix})='{key}' THEN '{category}'"
        for key, category in sorted(pairs.items())
    )
    return f"CASE {clauses} ELSE 'server' END"


async def _install_legacy_ui_bridge(bot) -> None:
    """L'ancien composant +setup écrit encore dans log_settings.

    On garde cette table comme *entrée de compatibilité* uniquement : deux triggers
    répercutent immédiatement l'écriture dans log_config. Le transport ne lit jamais
    log_settings. Ce bridge peut disparaître quand l'ancien composant UI sera retiré.
    """
    columns = await _table_columns(bot, "log_settings")
    if not {"guild_id", "log_type", "channel_id", "enabled"}.issubset(columns):
        return

    case_sql = _legacy_case_sql()
    await bot.db.execute("DROP TRIGGER IF EXISTS sentrix_log_settings_to_config_insert")
    await bot.db.execute("DROP TRIGGER IF EXISTS sentrix_log_settings_to_config_update")
    await bot.db.execute(
        "CREATE TRIGGER sentrix_log_settings_to_config_insert "
        "AFTER INSERT ON log_settings BEGIN "
        "INSERT INTO log_config (guild_id,category,channel_id,enabled,updated_at) "
        f"VALUES (NEW.guild_id,{case_sql},NEW.channel_id,NEW.enabled,strftime('%s','now')) "
        "ON CONFLICT(guild_id,category) DO UPDATE SET "
        "channel_id=excluded.channel_id,enabled=excluded.enabled,updated_at=excluded.updated_at; "
        "END"
    )
    await bot.db.execute(
        "CREATE TRIGGER sentrix_log_settings_to_config_update "
        "AFTER UPDATE OF channel_id,enabled ON log_settings BEGIN "
        "INSERT INTO log_config (guild_id,category,channel_id,enabled,updated_at) "
        f"VALUES (NEW.guild_id,{case_sql},NEW.channel_id,NEW.enabled,strftime('%s','now')) "
        "ON CONFLICT(guild_id,category) DO UPDATE SET "
        "channel_id=excluded.channel_id,enabled=excluded.enabled,updated_at=excluded.updated_at; "
        "END"
    )


async def _ensure_log_config_schema(bot) -> None:
    key = id(bot.db)
    if key in _SCHEMA_READY:
        return

    columns = await _table_columns(bot, "log_config")
    if not columns:
        await bot.db.execute(
            "CREATE TABLE IF NOT EXISTS log_config ("
            "guild_id INTEGER NOT NULL,category TEXT NOT NULL,channel_id INTEGER,"
            "enabled INTEGER NOT NULL DEFAULT 1,updated_at INTEGER NOT NULL DEFAULT 0,"
            "PRIMARY KEY (guild_id,category))"
        )
    elif "category" not in columns and "log_type" in columns:
        rows = await bot.db.fetchall(
            "SELECT guild_id,log_type,channel_id,enabled FROM log_config"
        )
        await bot.db.execute("DROP TABLE IF EXISTS log_config_category_migration")
        await bot.db.execute(
            "CREATE TABLE log_config_category_migration ("
            "guild_id INTEGER NOT NULL,category TEXT NOT NULL,channel_id INTEGER,"
            "enabled INTEGER NOT NULL DEFAULT 1,updated_at INTEGER NOT NULL DEFAULT 0,"
            "PRIMARY KEY (guild_id,category))"
        )
        for row in rows:
            category = legacy_to_category(str(row["log_type"])) or "server"
            await bot.db.execute(
                "INSERT INTO log_config_category_migration "
                "(guild_id,category,channel_id,enabled,updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(guild_id,category) DO UPDATE SET "
                "channel_id=COALESCE(log_config_category_migration.channel_id,excluded.channel_id),"
                "enabled=CASE WHEN log_config_category_migration.channel_id IS NULL "
                "THEN excluded.enabled ELSE log_config_category_migration.enabled END,"
                "updated_at=MAX(log_config_category_migration.updated_at,excluded.updated_at)",
                (
                    int(row["guild_id"]),
                    category,
                    int(row["channel_id"]) if row["channel_id"] else None,
                    int(bool(row["enabled"])),
                    _now(),
                ),
            )
        await bot.db.execute("DROP TABLE log_config")
        await bot.db.execute(
            "ALTER TABLE log_config_category_migration RENAME TO log_config"
        )
        logger.warning("Migration log_config log_type -> category terminée (%s lignes).", len(rows))

    columns = await _table_columns(bot, "log_config")
    if "updated_at" not in columns:
        await bot.db.execute(
            "ALTER TABLE log_config ADD COLUMN updated_at INTEGER NOT NULL DEFAULT 0"
        )
        await bot.db.execute(
            "UPDATE log_config SET updated_at=strftime('%s','now') WHERE updated_at=0"
        )
    if "enabled" not in columns:
        await bot.db.execute(
            "ALTER TABLE log_config ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1"
        )

    await _install_legacy_ui_bridge(bot)
    _SCHEMA_READY.add(key)


async def _guild_config(bot, guild_id: int):
    try:
        return await bot.db.get_guild_config(guild_id)
    except Exception:
        return None


async def _legacy_log_settings(
    bot, guild_id: int, category: str
) -> tuple[int | None, bool | None]:
    """Lecture de migration uniquement, jamais utilisée pour router un envoi."""
    columns = await _table_columns(bot, "log_settings")
    if not {"guild_id", "log_type", "channel_id", "enabled"}.issubset(columns):
        return None, None
    select = "log_type,channel_id,enabled"
    if "updated_at" in columns:
        select += ",updated_at"
    else:
        select += ",0 AS updated_at"
    try:
        rows = await bot.db.fetchall(
            f"SELECT {select} FROM log_settings WHERE guild_id=?",
            (int(guild_id),),
        )
    except Exception:
        return None, None

    candidates = []
    for row in rows:
        if legacy_to_category(str(row["log_type"])) != category:
            continue
        candidates.append(
            (
                1 if row["channel_id"] else 0,
                int(row["updated_at"] or 0),
                int(row["channel_id"]) if row["channel_id"] else None,
                bool(row["enabled"]),
            )
        )
    if not candidates:
        return None, None
    candidates.sort(reverse=True)
    _has_channel, _updated, channel_id, enabled = candidates[0]
    return channel_id, enabled


async def _legacy_channel_id(bot, guild_id: int, category: str) -> int | None:
    """Migration des anciennes colonnes guild_config, uniquement si log_config est vide."""
    column = _LEGACY_COLUMNS.get(category)
    if not column:
        return None
    conf = await _guild_config(bot, int(guild_id))
    if conf is None:
        return None
    try:
        value = conf[column]
    except (KeyError, IndexError, TypeError):
        value = None
    return int(value) if value else None


async def _ensure_legacy_ui_row(
    bot,
    guild_id: int,
    category: str,
    *,
    channel_id: int | None,
    enabled: bool,
) -> None:
    """Garantit que l'ancien UPDATE du +setup touche bien une ligne et déclenche le bridge."""
    columns = await _table_columns(bot, "log_settings")
    if not {"guild_id", "log_type", "channel_id", "enabled"}.issubset(columns):
        return
    now_ts = _now()
    try:
        if {"created_at", "updated_at"}.issubset(columns):
            await bot.db.execute(
                "INSERT INTO log_settings "
                "(guild_id,log_type,enabled,channel_id,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(guild_id,log_type) DO NOTHING",
                (guild_id, category, 1 if enabled else 0, channel_id, now_ts, now_ts),
            )
        else:
            await bot.db.execute(
                "INSERT INTO log_settings (guild_id,log_type,enabled,channel_id) "
                "VALUES (?,?,?,?) ON CONFLICT(guild_id,log_type) DO NOTHING",
                (guild_id, category, 1 if enabled else 0, channel_id),
            )
    except Exception:
        logger.debug("Création ligne UI legacy ignorée %s/%s", guild_id, category, exc_info=True)


async def _ensure_category_row(bot, guild_id: int, category: str) -> dict[str, Any]:
    await _ensure_log_config_schema(bot)
    canonical = category if category in CATEGORIES else category_for(category)
    row = await bot.db.fetchone(
        "SELECT guild_id,category,channel_id,enabled,updated_at FROM log_config "
        "WHERE guild_id=? AND category=?",
        (int(guild_id), canonical),
    )

    # Une ligne canonique non vide gagne toujours.
    if row is not None and row["channel_id"]:
        result = dict(row)
        await _ensure_legacy_ui_row(
            bot,
            int(guild_id),
            canonical,
            channel_id=int(row["channel_id"]),
            enabled=bool(row["enabled"]),
        )
        return result

    # Migration prudente : log_settings d'abord, puis anciennes colonnes guild_config.
    legacy_channel, legacy_enabled = await _legacy_log_settings(
        bot, int(guild_id), canonical
    )
    source = "log_settings" if legacy_channel is not None else None
    if legacy_channel is None:
        legacy_channel = await _legacy_channel_id(bot, int(guild_id), canonical)
        source = "guild_config" if legacy_channel is not None else None

    if row is None:
        enabled = bool(legacy_enabled) if legacy_enabled is not None else True
        await bot.db.execute(
            "INSERT INTO log_config (guild_id,category,channel_id,enabled,updated_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(guild_id,category) DO NOTHING",
            (
                int(guild_id),
                canonical,
                legacy_channel,
                1 if enabled else 0,
                _now(),
            ),
        )
    elif legacy_channel is not None:
        # Remplit uniquement une route vide. Une vraie route canonique n'est jamais écrasée.
        enabled = bool(legacy_enabled) if legacy_enabled is not None else bool(row["enabled"])
        await bot.db.execute(
            "UPDATE log_config SET channel_id=?,enabled=?,updated_at=? "
            "WHERE guild_id=? AND category=? AND channel_id IS NULL",
            (
                legacy_channel,
                1 if enabled else 0,
                _now(),
                int(guild_id),
                canonical,
            ),
        )
        logger.warning(
            "MIGRATION LOGS route restaurée guild=%s category=%s channel=%s source=%s",
            guild_id,
            canonical,
            legacy_channel,
            source,
        )

    final = await bot.db.fetchone(
        "SELECT guild_id,category,channel_id,enabled,updated_at FROM log_config "
        "WHERE guild_id=? AND category=?",
        (int(guild_id), canonical),
    )
    result = dict(final) if final is not None else {
        "guild_id": int(guild_id),
        "category": canonical,
        "channel_id": None,
        "enabled": 1,
        "updated_at": _now(),
    }
    await _ensure_legacy_ui_row(
        bot,
        int(guild_id),
        canonical,
        channel_id=int(result["channel_id"]) if result.get("channel_id") else None,
        enabled=bool(result.get("enabled", 1)),
    )
    return result


async def _mirror_legacy_setting(
    bot,
    guild_id: int,
    category: str,
    *,
    channel_id: int | None,
    enabled: bool,
) -> None:
    """Compatibilité UI uniquement. Le runtime ne relit jamais cette valeur."""
    await _ensure_legacy_ui_row(
        bot,
        int(guild_id),
        category,
        channel_id=channel_id,
        enabled=enabled,
    )
    columns = await _table_columns(bot, "log_settings")
    if not {"guild_id", "log_type", "channel_id", "enabled"}.issubset(columns):
        return
    now_ts = _now()
    if "updated_at" in columns:
        await bot.db.execute(
            "UPDATE log_settings SET channel_id=?,enabled=?,updated_at=? "
            "WHERE guild_id=? AND log_type=?",
            (channel_id, 1 if enabled else 0, now_ts, int(guild_id), category),
        )
    else:
        await bot.db.execute(
            "UPDATE log_settings SET channel_id=?,enabled=? "
            "WHERE guild_id=? AND log_type=?",
            (channel_id, 1 if enabled else 0, int(guild_id), category),
        )


async def get_log_config(bot, guild_id: int, category: str) -> dict | None:
    canonical = category if category in CATEGORIES else category_for(category)
    row = await _ensure_category_row(bot, int(guild_id), canonical)
    return {
        "guild_id": int(row["guild_id"]),
        "category": canonical,
        "channel_id": int(row["channel_id"]) if row.get("channel_id") else None,
        "enabled": bool(row.get("enabled", 1)),
        "updated_at": int(row.get("updated_at") or 0),
    }


async def set_log_config(
    bot,
    guild_id: int,
    category: str,
    *,
    channel_id: int | None,
    enabled: bool,
) -> dict:
    """Écriture atomique unique utilisée par les nouveaux écrans de configuration."""
    canonical = category if category in CATEGORIES else category_for(category)
    if canonical not in CATEGORIES:
        raise ValueError(f"unknown_log_category:{category}")
    await _ensure_log_config_schema(bot)
    normalized = int(channel_id) if channel_id is not None else None
    await bot.db.execute(
        "INSERT INTO log_config (guild_id,category,channel_id,enabled,updated_at) "
        "VALUES (?,?,?,?,?) ON CONFLICT(guild_id,category) DO UPDATE SET "
        "channel_id=excluded.channel_id,enabled=excluded.enabled,updated_at=excluded.updated_at",
        (int(guild_id), canonical, normalized, 1 if enabled else 0, _now()),
    )
    await _mirror_legacy_setting(
        bot,
        int(guild_id),
        canonical,
        channel_id=normalized,
        enabled=bool(enabled),
    )
    return await get_log_config(bot, int(guild_id), canonical)


async def get_log_setting(bot, guild_id: int, log_type: str) -> dict:
    category = log_type if log_type in CATEGORIES else category_for(log_type)
    config = await get_log_config(bot, int(guild_id), category)
    if config is None:
        return {**DEFAULT_LOG_SETTING, "category": category}
    channel_id = config["channel_id"]
    return {
        "enabled": bool(config["enabled"]),
        "channel_id": channel_id,
        "dedicated_channel_id": channel_id,
        "fallback_channel_id": None,
        "category": category,
        "include_content": True,
        "include_attachments": True,
        "include_actor": True,
        "include_reason": True,
    }


async def get_all_log_settings(bot, guild_id: int) -> dict[str, dict]:
    return {
        category: await get_log_setting(bot, int(guild_id), category)
        for category in LOG_TYPES
    }


async def set_log_channel(
    bot, guild_id: int, log_type: str, channel_id: int | None
) -> dict:
    category = log_type if log_type in CATEGORIES else category_for(log_type)
    current = await get_log_config(bot, int(guild_id), category)
    enabled = bool(current["enabled"]) if current is not None else channel_id is not None
    saved = await set_log_config(
        bot,
        int(guild_id),
        category,
        channel_id=channel_id,
        enabled=enabled if channel_id is None else True,
    )
    return await get_log_setting(bot, int(guild_id), saved["category"])


async def set_log_enabled(
    bot, guild_id: int, log_type: str, enabled: bool
) -> dict:
    category = log_type if log_type in CATEGORIES else category_for(log_type)
    current = await get_log_config(bot, int(guild_id), category)
    channel_id = current["channel_id"] if current else None
    if enabled and channel_id is None:
        raise ValueError("channel_required")
    saved = await set_log_config(
        bot,
        int(guild_id),
        category,
        channel_id=channel_id,
        enabled=bool(enabled),
    )
    return await get_log_setting(bot, int(guild_id), saved["category"])


def validate_channel(
    guild: discord.Guild,
    channel_id: int | None,
    *,
    needs_file: bool = False,
):
    if not channel_id:
        return False, "aucun salon configuré"
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return False, "salon introuvable ou non textuel"
    me = guild.me
    if me is None:
        return False, "membre bot introuvable dans le cache du serveur"
    perms = channel.permissions_for(me)
    if not perms.view_channel:
        return False, "le bot ne peut pas voir ce salon"
    if not perms.send_messages:
        return False, "le bot ne peut pas envoyer de messages dans ce salon"
    if not perms.embed_links:
        return False, "le bot ne peut pas intégrer d'embed dans ce salon"
    if not perms.read_message_history:
        return False, "le bot ne peut pas lire l'historique de ce salon"
    if needs_file and not perms.attach_files:
        return False, "le bot ne peut pas joindre de fichiers dans ce salon"
    return True, "ok"


def _event_from_key(event_key: str | None) -> str | None:
    if not event_key:
        return None
    parts = str(event_key).split(":")
    if len(parts) < 2:
        return None
    candidate = canonical_event_type(parts[1])
    return candidate if candidate in LOG_REGISTRY else None


async def route_for(bot, guild: discord.Guild, log_type: str) -> tuple[discord.TextChannel | None, str, str | None]:
    category = category_for(log_type)
    config = await get_log_config(bot, guild.id, category)
    if config is None:
        return None, category, "NO CONFIG"
    if not config["enabled"]:
        return None, category, "DISABLED"
    if config["channel_id"] is None:
        return None, category, "NO CHANNEL"
    channel = guild.get_channel(int(config["channel_id"]))
    if not isinstance(channel, discord.TextChannel):
        return None, category, "CHANNEL GONE"
    return channel, category, None


async def send_log(
    bot,
    guild: discord.Guild,
    log_type: str,
    embed: discord.Embed,
    file: discord.File | None = None,
    *,
    view: discord.ui.View | None = None,
    event_key: str | None = None,
    identity_name: str | None = None,
    identity_id: int | None = None,
    identity_icon: str | None = None,
) -> bool:
    """Pipeline unique : event -> catégorie -> log_config -> validation -> Components V2."""
    logger.warning(
        "SXTRACE 3 SEND_LOG guild=%s log_type=%s event_key=%s title=%r primary=%s "
        "producer_env=%r wrapped_by=%s",
        getattr(guild, "id", None), log_type, event_key,
        (embed.title or "")[:60], is_primary_process(),
        os.getenv("SENTRIX_LOG_PRODUCER"),
        getattr(send_log, "__name__", "?"),
    )
    if not is_primary_process():
        logger.warning(
            "SXTRACE 3 SEND_LOG skipped=NOT_PRIMARY_PROCESS guild=%s",
            getattr(guild, "id", None),
        )
        return False

    # Les listeners officiels créent un event_key avec le vrai événement. Il gagne sur
    # les anciennes pseudo-clés comme log_server/log_roles et supprime leur ambiguïté.
    event_type = _event_from_key(event_key) or canonical_event_type(
        log_type, embed.title or "", embed.description or ""
    )
    category = category_for(event_type, embed.title or "", embed.description or "")

    from utils import embeds as embeds_mod
    try:
        rendered = embeds_mod.normalize_log(embed)
    except Exception:
        logger.exception("Normalisation du log échouée; embed métier conservé.")
        rendered = embed.copy()

    semantic_key = semantic_event_key(guild.id, event_type, rendered)
    if _is_duplicate(event_key) or _is_duplicate(semantic_key):
        logger.warning(
            "SXTRACE 5 GATE guild=%s type=%s category=%s skipped=DUPLICATE "
            "event_key=%s semantic_key=%s",
            guild.id, event_type, category, event_key, semantic_key,
        )
        return False

    config = await get_log_config(bot, guild.id, category)
    channel_id = config["channel_id"] if config else None
    logger.warning(
        "SXTRACE 4 ROUTE guild=%s log_type=%s category=%s channel_id=%s enabled=%s "
        "updated_at=%s reason=%s",
        guild.id, event_type, category, channel_id,
        (config or {}).get("enabled"), (config or {}).get("updated_at"),
        "NO CONFIG" if config is None
        else "DISABLED" if not config["enabled"]
        else "NO CHANNEL" if channel_id is None
        else "OK",
    )
    if config is None:
        logger.info(
            "SENTRIX ROUTE log_type=%s category=%s channel_id=None source=log_config skipped=NO CONFIG",
            event_type,
            category,
        )
        return False
    if not config["enabled"]:
        logger.info(
            "SENTRIX ROUTE log_type=%s category=%s channel_id=%s source=log_config skipped=DISABLED",
            event_type,
            category,
            channel_id,
        )
        return False
    if channel_id is None:
        logger.info(
            "SENTRIX ROUTE log_type=%s category=%s channel_id=None source=log_config skipped=NO CHANNEL",
            event_type,
            category,
        )
        return False

    ok, reason = validate_channel(guild, channel_id, needs_file=True)
    if not ok:
        logger.warning(
            "SXTRACE 5 GATE guild=%s category=%s channel_id=%s dedup=passed "
            "skipped=PERMISSIONS reason=%s",
            guild.id, category, channel_id, reason,
        )
        logger.warning(
            "SENTRIX ROUTE log_type=%s category=%s channel_id=%s source=log_config skipped=%s",
            event_type,
            category,
            channel_id,
            reason,
        )
        return False

    channel = guild.get_channel(int(channel_id))
    logger.warning(
        "SXTRACE 5 GATE guild=%s category=%s channel_id=%s dedup=passed permissions=ok "
        "channel_resolved=%s transport=%s.%s",
        guild.id, category, channel_id, channel is not None,
        getattr(send_wide_log, "__module__", "?"),
        getattr(send_wide_log, "__name__", "?"),
    )
    logger.info(
        "SENTRIX ROUTE log_type=%s category=%s channel_id=%s source=log_config",
        event_type,
        category,
        channel_id,
    )
    return await send_wide_log(
        channel,
        rendered,
        log_type=event_type,
        old_view=view,
        extra_file=file,
        identity_name=identity_name,
        identity_id=identity_id,
        identity_icon=identity_icon,
    )


async def send_test_log(
    bot,
    guild: discord.Guild,
    log_type: str,
    author: discord.abc.User,
) -> tuple[bool, str]:
    category = log_type if log_type in CATEGORIES else category_for(log_type)
    config = await get_log_config(bot, guild.id, category)
    if config is None or not config["enabled"]:
        return False, "Cette catégorie de logs est désactivée."
    ok, reason = validate_channel(guild, config["channel_id"], needs_file=True)
    if not ok:
        return False, f"Impossible d'envoyer le test : {reason}."

    from utils import embeds as embeds_mod
    test_embed = embeds_mod.log_embed(
        "Test de log",
        description=(
            f"<@{author.id}> a lancé un test de la catégorie "
            f"**{CATEGORIES.get(category, category)}**."
        ),
    )
    channel = guild.get_channel(int(config["channel_id"]))
    sent = await send_wide_log(
        channel,
        test_embed,
        log_type=category,
        identity_name=getattr(author, "display_name", None)
        or getattr(author, "name", None),
        identity_id=author.id,
        identity_icon=str(
            getattr(getattr(author, "display_avatar", None), "url", "") or ""
        )
        or None,
    )
    if sent:
        return True, f"Test Components V2 envoyé dans {channel.mention}."
    return False, "Échec du renderer Components V2. Vérifiez Railway."


__all__ = [
    "CATEGORY_ORDER", "DEFAULT_LOG_SETTING", "LOG_ALLOWED_MENTIONS", "LOG_TYPES",
    "LogActionsView", "RevealIdButton", "_ensure_category_row", "_ensure_log_config_schema",
    "_legacy_channel_id", "_legacy_log_settings", "_mirror_legacy_setting",
    "categories_with_types", "get_all_log_settings", "get_log_config", "get_log_setting",
    "is_primary_process", "log_actions", "make_event_key", "route_for", "semantic_event_key",
    "send_log", "send_test_log", "set_log_channel", "set_log_config", "set_log_enabled",
    "validate_channel",
]
