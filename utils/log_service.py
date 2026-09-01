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
    title, description = embed.title or "", embed.description or ""
    event_type = canonical_event_type(log_type, title, description)
    if event_type not in LOG_REGISTRY:
        # log_type etait une CATEGORIE ("moderation") et non un type d'evenement :
        # canonical_event_type la renvoie telle quelle sans jamais lire le texte. Les
        # commandes de sanction passent la categorie, les listeners Discord passent
        # l'evenement — sans cette relecture, les deux sources ne partageaient aucune
        # cle semantique et un meme kick sortait deux fois.
        event_type = canonical_event_type("", title, description)
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
        [str(title), str(description)]
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


async def _ensure_log_config_schema(bot) -> None:
    """Filet de sécurité : la table canonique est créée par ``Database.connect()``.

    Aucun trigger, aucun pont vers ``log_settings``. Cette table a été migrée puis
    archivée une seule fois par ``Database._migrate_logs()`` ; le runtime ne la lit ni
    ne l'écrit plus jamais.
    """
    key = id(bot.db)
    if key in _SCHEMA_READY:
        return
    await bot.db.execute(
        "CREATE TABLE IF NOT EXISTS log_config ("
        "guild_id INTEGER NOT NULL, category TEXT NOT NULL, channel_id INTEGER, "
        "enabled INTEGER NOT NULL DEFAULT 1, updated_at INTEGER NOT NULL DEFAULT 0, "
        "PRIMARY KEY (guild_id, category))"
    )
    _SCHEMA_READY.add(key)


async def _guild_config(bot, guild_id: int):
    try:
        return await bot.db.get_guild_config(guild_id)
    except Exception:
        return None


async def _ensure_category_row(bot, guild_id: int, category: str) -> dict[str, Any]:
    """Lecture pure de ``log_config``. N'écrit jamais ailleurs, ne migre rien."""
    await _ensure_log_config_schema(bot)
    canonical = category if category in CATEGORIES else category_for(category)
    row = await bot.db.fetchone(
        "SELECT guild_id, category, channel_id, enabled, updated_at FROM log_config "
        "WHERE guild_id=? AND category=?",
        (int(guild_id), canonical),
    )
    if row is not None:
        return dict(row)
    return {
        "guild_id": int(guild_id),
        "category": canonical,
        "channel_id": None,
        "enabled": 1,
        "updated_at": 0,
    }


# --------------------------------------------------------------------------
# Cache de lecture du routage
#
# Mesure : get_log_config etait appele a chaque message. C'est de la CONFIGURATION,
# donc l'invalidation est explicite dans set_log_config, seul point d'ecriture du
# runtime (la migration de database/db.py, elle, tourne au demarrage avant toute
# lecture, quand le cache est encore vide).
#
# Piege evite : set_log_config relit la base APRES ecriture et leve si elle ne
# contient pas ce qui vient d'etre demande. C'est ce controle qui empeche +setup
# d'afficher « ACTIF » pour une route jamais ecrite. Cette relecture-la doit donc
# TOUJOURS toucher la base : elle passe par fresh=True, jamais par le cache.
_CONFIG_CACHE: dict[tuple[int, str], tuple[float, dict]] = {}
_CONFIG_CACHE_TTL = 30.0


def invalidate_log_config(guild_id: int | None = None, category: str | None = None) -> None:
    """Purge le cache de routage. Sans argument : tout."""
    if guild_id is None:
        _CONFIG_CACHE.clear()
        return
    if category is None:
        for key in [k for k in _CONFIG_CACHE if k[0] == int(guild_id)]:
            _CONFIG_CACHE.pop(key, None)
        return
    _CONFIG_CACHE.pop((int(guild_id), str(category)), None)


async def get_log_config(
    bot, guild_id: int, category: str, *, fresh: bool = False
) -> dict | None:
    canonical = category if category in CATEGORIES else category_for(category)
    key = (int(guild_id), canonical)
    if not fresh:
        cached = _CONFIG_CACHE.get(key)
        if cached is not None and (time.monotonic() - cached[0]) < _CONFIG_CACHE_TTL:
            return dict(cached[1])
    row = await _ensure_category_row(bot, int(guild_id), canonical)
    result = {
        "guild_id": int(row["guild_id"]),
        "category": canonical,
        "channel_id": int(row["channel_id"]) if row.get("channel_id") else None,
        "enabled": bool(row.get("enabled", 1)),
        "updated_at": int(row.get("updated_at") or 0),
    }
    if len(_CONFIG_CACHE) > 5000:
        _CONFIG_CACHE.clear()
    _CONFIG_CACHE[key] = (time.monotonic(), dict(result))
    return dict(result)


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
    # Relecture systématique : l'appelant reçoit ce que la base contient vraiment, jamais
    # la valeur qu'il vient de demander. C'est ce qui empêche un panneau d'afficher
    # "ACTIF" pour une route qui n'a pas été écrite.
    invalidate_log_config(guild_id, canonical)
    # fresh=True : la confirmation doit venir de la BASE, jamais du cache. Sans ca, une
    # ecriture qui n'aboutit pas serait confirmee par la valeur precedente.
    saved = await get_log_config(bot, int(guild_id), canonical, fresh=True)
    if saved is None or saved.get("channel_id") != normalized:
        logger.error(
            "SENTRIX LOG WRITE FAILED guild=%s category=%s demande=%s relu=%s",
            guild_id, canonical, normalized, (saved or {}).get("channel_id"),
        )
        raise RuntimeError(f"log_config_write_failed:{canonical}")
    return saved


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
    "categories_with_types", "get_all_log_settings", "get_log_config", "get_log_setting",
    "is_primary_process", "log_actions", "make_event_key", "route_for", "semantic_event_key",
    "send_log", "send_test_log", "set_log_channel", "set_log_config", "set_log_enabled",
    "validate_channel",
]
