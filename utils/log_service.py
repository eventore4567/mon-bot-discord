"""Transport officiel et unique des journaux Discord SentriX.

Routage : événement -> catégorie -> salon dédié -> salon général de repli.
Rendu : ``send_wide_log`` Components V2 uniquement.
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections import OrderedDict
from typing import Any

import discord

from utils.log_categories import CATEGORIES, CATEGORY_ORDER as CATEGORY_KEYS, canonical_event_type, category_for, resolve
from utils.wide_logs import send_wide_log

logger = logging.getLogger("bot")

# Contrat public conservé pour /setup, diagnostics et anciens modules. Les clés sont
# désormais les catégories configurables, pas les événements individuels.
LOG_TYPES: dict[str, dict[str, Any]] = {
    "moderation": {"label": "Modération", "category": "Modération", "legacy_column": "log_moderation", "emits": True},
    "messages": {"label": "Messages", "category": "Messages", "legacy_column": "log_messages", "emits": True},
    "members": {"label": "Membres", "category": "Membres", "legacy_column": "log_members", "emits": True},
    "channels": {"label": "Salons", "category": "Salons", "legacy_column": "log_server", "emits": True},
    "roles": {"label": "Rôles", "category": "Rôles", "legacy_column": "log_roles", "emits": True},
    "voice": {"label": "Vocal", "category": "Vocal", "legacy_column": "log_voice", "emits": True},
    "server": {"label": "Serveur", "category": "Serveur", "legacy_column": "log_channel", "emits": True},
    "tickets": {"label": "Tickets", "category": "Tickets", "legacy_column": "ticket_log_channel", "emits": True},
    "protection": {"label": "Protection", "category": "Protection", "legacy_column": "log_automod", "emits": True},
}
CATEGORY_ORDER = [CATEGORIES[key] for key in CATEGORY_KEYS]

DEFAULT_LOG_SETTING = {
    "enabled": True,
    "channel_id": None,
    "dedicated_channel_id": None,
    "include_content": True,
    "include_attachments": True,
    "include_actor": True,
    "include_reason": True,
}

LOG_ALLOWED_MENTIONS = discord.AllowedMentions(everyone=False, users=False, roles=False, replied_user=False)

_DEDUP_TTL = 8.0
_DEDUP_MAX = 4096
_recent_event_keys: OrderedDict[str, float] = OrderedDict()
_SCHEMA_READY: set[int] = set()

_LEGACY_SETTING_KEYS = {
    "moderation": ("moderation",),
    "messages": ("messages",),
    "members": ("members",),
    "channels": ("server", "channels"),
    "roles": ("roles",),
    "voice": ("voice",),
    "server": ("system",),
    "tickets": ("tickets",),
    "protection": ("automod", "protection"),
}


def is_primary_process() -> bool:
    raw = (os.getenv("SENTRIX_LOG_PRODUCER") or "").strip().casefold()
    return raw not in {"0", "false", "no", "off", "disabled"}


def categories_with_types() -> dict[str, list[str]]:
    return {CATEGORIES[key]: [key] for key in CATEGORY_KEYS if key in LOG_TYPES}


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
    return ":".join(str(part) for part in (
        guild_id, event_type, target_id or 0, executor_id or 0,
        audit_log_id or 0, message_id or 0, discriminator or "",
    ))


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
        "member_ban", "member_unban", "member_kick", "member_timeout",
        "member_untimeout", "member_warn",
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
        super().__init__(label=label[:80], style=discord.ButtonStyle.secondary, custom_id=f"sxid:{self.entity_id}", row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"`{self.entity_id}`",
            ephemeral=True,
            allowed_mentions=LOG_ALLOWED_MENTIONS,
        )


class LogActionsView(discord.ui.View):
    def __init__(self, *, jump_url: str | None = None, ids: list[tuple[str, int]] | None = None):
        super().__init__(timeout=None)
        if jump_url:
            self.add_item(discord.ui.Button(label="Voir le message", style=discord.ButtonStyle.link, url=jump_url, row=0))
        for label, entity_id in (ids or [])[:4]:
            self.add_item(RevealIdButton(label, entity_id, row=0))


def log_actions(*, jump_url: str | None = None, ids: list[tuple[str, int]] | None = None) -> LogActionsView | None:
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


async def _ensure_log_config_schema(bot) -> None:
    key = id(bot.db)
    if key in _SCHEMA_READY:
        return

    columns = await _table_columns(bot, "log_config")
    if not columns:
        await bot.db.execute(
            "CREATE TABLE IF NOT EXISTS log_config ("
            "guild_id INTEGER NOT NULL, category TEXT NOT NULL, channel_id INTEGER, "
            "enabled INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (guild_id, category))"
        )
        _SCHEMA_READY.add(key)
        return

    if "category" in columns:
        _SCHEMA_READY.add(key)
        return

    if "log_type" not in columns:
        logger.warning("Schéma log_config non reconnu: %s", sorted(columns))
        return

    rows = await bot.db.fetchall("SELECT guild_id,log_type,channel_id,enabled FROM log_config")
    grouped: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        guild_id = int(row["guild_id"])
        category = category_for(str(row["log_type"]))
        channel_id = int(row["channel_id"]) if row["channel_id"] else None
        enabled = bool(row["enabled"])
        current = grouped.get((guild_id, category))
        if current is None:
            grouped[(guild_id, category)] = {"channel_id": channel_id, "enabled": enabled}
            continue
        current["enabled"] = bool(current["enabled"] or enabled)
        if current["channel_id"] is None and channel_id is not None:
            current["channel_id"] = channel_id

    await bot.db.execute("DROP TABLE IF EXISTS log_config_category_migration")
    await bot.db.execute(
        "CREATE TABLE log_config_category_migration ("
        "guild_id INTEGER NOT NULL, category TEXT NOT NULL, channel_id INTEGER, "
        "enabled INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (guild_id, category))"
    )
    for (guild_id, category), setting in grouped.items():
        await bot.db.execute(
            "INSERT INTO log_config_category_migration (guild_id,category,channel_id,enabled) VALUES (?,?,?,?)",
            (guild_id, category, setting["channel_id"], 1 if setting["enabled"] else 0),
        )
    await bot.db.execute("DROP TABLE log_config")
    await bot.db.execute("ALTER TABLE log_config_category_migration RENAME TO log_config")
    logger.warning("Migration log_config par catégorie terminée: %s routes préservées.", len(grouped))
    _SCHEMA_READY.add(key)


async def _guild_config(bot, guild_id: int):
    try:
        return await bot.db.get_guild_config(guild_id)
    except Exception:
        return None


async def _general_channel_id(bot, guild_id: int) -> int | None:
    conf = await _guild_config(bot, guild_id)
    if not conf:
        return None
    try:
        value = conf["log_channel"]
    except (KeyError, IndexError, TypeError):
        value = None
    return int(value) if value else None


async def _legacy_channel_id(bot, guild_id: int, category: str) -> int | None:
    meta = LOG_TYPES.get(category, {})
    legacy_column = meta.get("legacy_column")
    conf = await _guild_config(bot, guild_id)
    if not conf or not legacy_column:
        return None
    try:
        value = conf[legacy_column]
    except (KeyError, IndexError, TypeError):
        value = None
    # ``server`` n'a jamais eu de salon dédié historique : log_channel est son repli.
    if category == "server":
        return None
    return int(value) if value else None


async def _legacy_log_settings(bot, guild_id: int, category: str) -> tuple[int | None, bool | None]:
    columns = await _table_columns(bot, "log_settings")
    if not columns or "log_type" not in columns:
        return None, None
    keys = _LEGACY_SETTING_KEYS.get(category, (category,))
    placeholders = ",".join("?" for _ in keys)
    try:
        rows = await bot.db.fetchall(
            f"SELECT log_type,channel_id,enabled FROM log_settings WHERE guild_id=? AND log_type IN ({placeholders})",
            (guild_id, *keys),
        )
    except Exception:
        return None, None
    chosen_channel = None
    enabled_values: list[bool] = []
    for row in rows:
        enabled_values.append(bool(row["enabled"]))
        if chosen_channel is None and row["channel_id"]:
            chosen_channel = int(row["channel_id"])
    enabled = any(enabled_values) if enabled_values else None
    return chosen_channel, enabled


async def _ensure_category_row(bot, guild_id: int, category: str) -> dict[str, Any]:
    await _ensure_log_config_schema(bot)
    row = await bot.db.fetchone(
        "SELECT guild_id,category,channel_id,enabled FROM log_config WHERE guild_id=? AND category=?",
        (guild_id, category),
    )
    if row is not None:
        return dict(row)

    migrated_channel, migrated_enabled = await _legacy_log_settings(bot, guild_id, category)
    if migrated_channel is None:
        migrated_channel = await _legacy_channel_id(bot, guild_id, category)
    enabled = True if migrated_enabled is None else bool(migrated_enabled)
    await bot.db.execute(
        "INSERT INTO log_config (guild_id,category,channel_id,enabled) VALUES (?,?,?,?) "
        "ON CONFLICT(guild_id,category) DO NOTHING",
        (guild_id, category, migrated_channel, 1 if enabled else 0),
    )
    return {
        "guild_id": guild_id,
        "category": category,
        "channel_id": migrated_channel,
        "enabled": 1 if enabled else 0,
    }


async def _mirror_legacy_setting(bot, guild_id: int, category: str, *, channel_id: int | None, enabled: bool) -> None:
    """Conserve les anciens écrans/modules qui lisent encore ``log_settings``."""
    columns = await _table_columns(bot, "log_settings")
    required = {"guild_id", "log_type", "channel_id", "enabled"}
    if not required.issubset(columns):
        return
    legacy_key = _LEGACY_SETTING_KEYS.get(category, (category,))[0]
    now_ts = _now()
    try:
        if {"created_at", "updated_at"}.issubset(columns):
            await bot.db.execute(
                "INSERT INTO log_settings (guild_id,log_type,enabled,channel_id,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(guild_id,log_type) DO UPDATE SET "
                "enabled=excluded.enabled,channel_id=excluded.channel_id,updated_at=excluded.updated_at",
                (guild_id, legacy_key, 1 if enabled else 0, channel_id, now_ts, now_ts),
            )
        else:
            await bot.db.execute(
                "INSERT INTO log_settings (guild_id,log_type,enabled,channel_id) VALUES (?,?,?,?) "
                "ON CONFLICT(guild_id,log_type) DO UPDATE SET enabled=excluded.enabled,channel_id=excluded.channel_id",
                (guild_id, legacy_key, 1 if enabled else 0, channel_id),
            )
    except Exception:
        logger.debug("Miroir log_settings ignoré pour %s/%s", guild_id, category, exc_info=True)


async def get_log_setting(bot, guild_id: int, log_type: str) -> dict:
    category, _emoji, _kind = resolve(log_type)
    row = await _ensure_category_row(bot, guild_id, category)
    dedicated = int(row["channel_id"]) if row.get("channel_id") else None
    general = await _general_channel_id(bot, guild_id)
    effective = dedicated or general
    return {
        "enabled": bool(row.get("enabled", 1)),
        "channel_id": effective,
        "dedicated_channel_id": dedicated,
        "fallback_channel_id": general if not dedicated else None,
        "category": category,
        "include_content": True,
        "include_attachments": True,
        "include_actor": True,
        "include_reason": True,
    }


async def get_all_log_settings(bot, guild_id: int) -> dict[str, dict]:
    return {category: await get_log_setting(bot, guild_id, category) for category in LOG_TYPES}


async def set_log_enabled(bot, guild_id: int, log_type: str, enabled: bool) -> dict:
    category, _emoji, _kind = resolve(log_type)
    current = await get_log_setting(bot, guild_id, category)
    if enabled and not current["channel_id"]:
        raise ValueError("channel_required")
    await bot.db.execute(
        "UPDATE log_config SET enabled=? WHERE guild_id=? AND category=?",
        (1 if enabled else 0, guild_id, category),
    )
    await _mirror_legacy_setting(
        bot, guild_id, category,
        channel_id=current.get("dedicated_channel_id"),
        enabled=bool(enabled),
    )
    return await get_log_setting(bot, guild_id, category)


async def set_log_channel(bot, guild_id: int, log_type: str, channel_id: int | None) -> dict:
    category, _emoji, _kind = resolve(log_type)
    row = await _ensure_category_row(bot, guild_id, category)
    enabled = bool(row.get("enabled", 1))
    await bot.db.execute(
        "UPDATE log_config SET channel_id=? WHERE guild_id=? AND category=?",
        (channel_id, guild_id, category),
    )
    await _mirror_legacy_setting(bot, guild_id, category, channel_id=channel_id, enabled=enabled)
    return await get_log_setting(bot, guild_id, category)


def validate_channel(guild: discord.Guild, channel_id: int | None, *, needs_file: bool = False):
    if not channel_id:
        return False, "aucun salon configuré"
    channel = guild.get_channel(int(channel_id))
    if channel is None:
        return False, "salon introuvable"
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
    if needs_file and not perms.attach_files:
        return False, "le bot ne peut pas joindre de fichiers dans ce salon"
    return True, "ok"


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
    """Point de sortie central : catégorie, déduplication puis Components V2."""
    if not is_primary_process():
        return False

    event_type = canonical_event_type(log_type, embed.title or "", embed.description or "")
    category, _emoji, _kind = resolve(event_type, embed.title or "", embed.description or "")

    from utils import embeds as embeds_mod
    try:
        rendered = embeds_mod.normalize_log(embed)
    except Exception:
        logger.exception("Normalisation du log échouée; embed métier conservé.")
        rendered = embed.copy()

    semantic_key = semantic_event_key(guild.id, event_type, rendered)
    if _is_duplicate(event_key) or _is_duplicate(semantic_key):
        logger.debug("Log dupliqué ignoré guild=%s type=%s", guild.id, event_type)
        return False

    try:
        setting = await get_log_setting(bot, guild.id, category)
    except Exception:
        logger.exception("Impossible de résoudre la configuration de log %s/%s.", guild.id, category)
        return False

    if not setting["enabled"]:
        logger.info("Log désactivé guild=%s category=%s type=%s", guild.id, category, event_type)
        return False

    ok, reason = validate_channel(guild, setting["channel_id"], needs_file=True)
    if not ok:
        logger.warning("Log non envoyé guild=%s category=%s type=%s: %s", guild.id, category, event_type, reason)
        return False

    channel = guild.get_channel(int(setting["channel_id"]))
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


async def send_test_log(bot, guild: discord.Guild, log_type: str, author: discord.abc.User) -> tuple[bool, str]:
    category, _emoji, _kind = resolve(log_type)
    setting = await get_log_setting(bot, guild.id, category)
    if not setting["enabled"]:
        return False, "Cette catégorie de logs est désactivée."
    ok, reason = validate_channel(guild, setting["channel_id"], needs_file=True)
    if not ok:
        return False, f"Impossible d'envoyer le test : {reason}."

    from utils import embeds as embeds_mod
    test_embed = embeds_mod.log_embed(
        "Test de log",
        description=f"<@{author.id}> a lancé un test de la catégorie **{CATEGORIES.get(category, category)}**.",
    )
    channel = guild.get_channel(int(setting["channel_id"]))
    sent = await send_wide_log(
        channel,
        test_embed,
        log_type=category,
        identity_name=getattr(author, "display_name", None) or getattr(author, "name", None),
        identity_id=author.id,
        identity_icon=str(getattr(getattr(author, "display_avatar", None), "url", "") or "") or None,
    )
    if sent:
        return True, f"Test Components V2 envoyé dans {channel.mention}."
    return False, "Échec du renderer Components V2. Vérifiez Railway."
