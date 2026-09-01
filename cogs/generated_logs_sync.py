"""Réconciliation légère et diagnostic des salons de logs SentriX.

Le runtime lit uniquement ``log_config``. L'ancien écran +setup écrit encore dans
``log_settings`` : tant que cet écran n'est pas totalement retiré, deux triggers SQLite
font uniquement office de pont d'écriture vers ``log_config``. Aucun envoi de log ne lit
``log_settings``.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata

import discord
from discord.ext import commands

from utils import log_categories, log_service

logger = logging.getLogger("bot.generated-logs-sync")

LOG_CHANNEL_ALIASES: dict[str, tuple[str, ...]] = {
    "moderation": ("logs-moderation", "logs-modération", "logs-modo"),
    "messages": ("logs-messages", "logs-message"),
    "members": ("logs-membre", "logs-membres", "logs-member", "logs-members"),
    "channels": ("logs-salons", "logs-channels", "logs-channel"),
    "roles": ("logs-roles", "logs-rôles", "logs-role", "logs-rôle"),
    "voice": ("logs-vocal", "logs-vocaux", "logs-voice"),
    "server": ("logs-serveur", "logs-server"),
    "tickets": ("logs-tickets", "logs-ticket"),
    "automod": ("automod", "logs-automod", "logs-securite", "logs-sécurité", "logs-security"),
    "spam": ("logs-spam", "logs-protect-spam-logs", "protect-spam-logs"),
    "raid": ("logs-raid", "raidprotect-logs", "raid-protect-logs", "anti-raid-logs"),
    "resources": ("logs-resources", "logs-ressources", "logs-dossiers", "logs-invitations"),
    "files": ("logs-files", "logs-fichiers"),
}

_CANONICAL = tuple(LOG_CHANNEL_ALIASES)
_CANONICAL_SQL = ",".join(f"'{item}'" for item in _CANONICAL)


def _sanitize_catalog() -> None:
    """Réaffirme les 13 catégories sans remplacer aucune fonction Python."""
    log_categories.CATEGORIES.pop("dossiers", None)
    log_service.LOG_TYPES.pop("dossiers", None)
    log_service.LOG_TYPES.pop("protection", None)
    log_categories.LOG_REGISTRY.update(
        {
            "invite_create": ("resources", "🔗", "success"),
            "invite_delete": ("resources", "🔗", "error"),
            "emoji_update": ("resources", "😀", "info"),
            "sticker_update": ("resources", "🧩", "info"),
            "webhook_update": ("resources", "🔗", "warning"),
            "automod_link": ("automod", "🔗", "error"),
            "automod_word": ("automod", "🛑", "error"),
            "automod_spam": ("spam", "🚫", "error"),
            "antiraid": ("raid", "🛡️", "error"),
        }
    )
    log_categories.CATEGORY_ORDER = tuple(
        key for key in log_categories.CATEGORIES if key in log_service.LOG_TYPES
    )
    log_service.CATEGORY_ORDER = [
        log_categories.CATEGORIES[key]
        for key in log_categories.CATEGORY_ORDER
    ]


def _plain(value: str) -> str:
    value = (value or "").strip()
    if "・" in value:
        value = value.split("・", 1)[1]
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold().replace("_", " ")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


_NORMALIZED = {
    category: frozenset(_plain(alias) for alias in aliases)
    for category, aliases in LOG_CHANNEL_ALIASES.items()
}


def _find_log_channel(guild: discord.Guild, category: str) -> discord.TextChannel | None:
    wanted = _NORMALIZED.get(category, frozenset())
    if not wanted:
        return None
    for channel in guild.text_channels:
        parent = getattr(channel, "category", None)
        parent_name = _plain(getattr(parent, "name", "")) if parent else ""
        if _plain(channel.name) in wanted and (
            "logs" in parent_name or ("sentrix" in parent_name and "log" in parent_name)
        ):
            return channel
    for channel in guild.text_channels:
        if _plain(channel.name) in wanted:
            return channel
    return None


async def _table_columns(bot: commands.Bot, table: str) -> set[str]:
    try:
        rows = await bot.db.fetchall(f"PRAGMA table_info({table})")
    except Exception:
        return set()
    result = set()
    for row in rows:
        try:
            result.add(str(row["name"]))
        except Exception:
            try:
                result.add(str(row[1]))
            except Exception:
                pass
    return result


async def _install_setup_bridge(bot: commands.Bot) -> None:
    """Fait suivre immédiatement les écritures du vieux +setup vers log_config."""
    columns = await _table_columns(bot, "log_settings")
    if not {"guild_id", "log_type", "channel_id", "enabled"}.issubset(columns):
        logger.warning("Pont Setup logs non installé : table log_settings absente/incompatible.")
        return

    # log_config est préparée par le service canonique avant d'installer les triggers.
    if bot.guilds:
        await log_service.get_log_config(bot, bot.guilds[0].id, "messages")

    updated_expr = "COALESCE(NEW.updated_at, strftime('%s','now'))" if "updated_at" in columns else "strftime('%s','now')"
    for name in ("sentrix_log_settings_insert", "sentrix_log_settings_update"):
        await bot.db.execute(f"DROP TRIGGER IF EXISTS {name}")

    await bot.db.execute(
        f"""
        CREATE TRIGGER sentrix_log_settings_insert
        AFTER INSERT ON log_settings
        WHEN NEW.log_type IN ({_CANONICAL_SQL})
        BEGIN
            INSERT INTO log_config (guild_id, category, channel_id, enabled, updated_at)
            VALUES (NEW.guild_id, NEW.log_type, NEW.channel_id, NEW.enabled, {updated_expr})
            ON CONFLICT(guild_id, category) DO UPDATE SET
                channel_id = excluded.channel_id,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at;
        END
        """
    )
    await bot.db.execute(
        f"""
        CREATE TRIGGER sentrix_log_settings_update
        AFTER UPDATE OF channel_id, enabled ON log_settings
        WHEN NEW.log_type IN ({_CANONICAL_SQL})
        BEGIN
            INSERT INTO log_config (guild_id, category, channel_id, enabled, updated_at)
            VALUES (NEW.guild_id, NEW.log_type, NEW.channel_id, NEW.enabled, {updated_expr})
            ON CONFLICT(guild_id, category) DO UPDATE SET
                channel_id = excluded.channel_id,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at;
        END
        """
    )
    logger.warning("Pont SQL +setup logs -> log_config installé pour %s catégories.", len(_CANONICAL))


async def _reconcile_recent_setup_rows(bot: commands.Bot) -> int:
    """Récupère aussi un choix fait dans +setup juste avant le déploiement du pont."""
    columns = await _table_columns(bot, "log_settings")
    if not {"guild_id", "log_type", "channel_id", "enabled"}.issubset(columns):
        return 0
    has_updated = "updated_at" in columns
    select_updated = ", updated_at" if has_updated else ""
    rows = await bot.db.fetchall(
        f"SELECT guild_id, log_type, channel_id, enabled{select_updated} FROM log_settings "
        f"WHERE log_type IN ({_CANONICAL_SQL})"
    )
    changed = 0
    for row in rows:
        category = str(row["log_type"])
        current = await log_service.get_log_config(bot, int(row["guild_id"]), category)
        legacy_updated = int(row["updated_at"] or 0) if has_updated else 0
        current_updated = int((current or {}).get("updated_at") or 0)
        legacy_channel = int(row["channel_id"]) if row["channel_id"] else None
        current_channel = int(current["channel_id"]) if current and current.get("channel_id") else None
        # Avec timestamp, la dernière action utilisateur gagne. Sans timestamp, on ne
        # remplace qu'une route canonique vide afin de ne pas écraser une vraie config.
        should_apply = (
            legacy_updated > current_updated
            if has_updated and legacy_updated
            else current_channel is None and legacy_channel is not None
        )
        if not should_apply:
            continue
        await log_service.set_log_config(
            bot,
            int(row["guild_id"]),
            category,
            channel_id=legacy_channel,
            enabled=bool(row["enabled"]) and legacy_channel is not None,
        )
        changed += 1
        logger.warning(
            "Setup log récupéré guild=%s category=%s channel=%s",
            row["guild_id"], category, legacy_channel,
        )
    return changed


async def sync_generated_logs(bot: commands.Bot, guild: discord.Guild) -> int:
    _sanitize_catalog()
    changed = 0
    for category in tuple(log_service.LOG_TYPES):
        try:
            config = await log_service.get_log_config(bot, guild.id, category)
        except Exception:
            logger.exception("Lecture log_config impossible guild=%s category=%s", guild.id, category)
            continue
        if config is None or not config.get("enabled") or config.get("channel_id"):
            continue
        channel = _find_log_channel(guild, category)
        if channel is None:
            continue
        try:
            await log_service.set_log_config(
                bot,
                guild.id,
                category,
                channel_id=channel.id,
                enabled=True,
            )
            changed += 1
            logger.warning(
                "Route de log générée restaurée guild=%s category=%s channel=%s",
                guild.id,
                category,
                channel.id,
            )
        except Exception:
            logger.exception(
                "Synchronisation log généré impossible guild=%s category=%s",
                guild.id,
                category,
            )
    return changed


class LogsDiagnostics(commands.Cog, name="LogsDiagnostics"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="logsdiag")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def logsdiag(self, ctx: commands.Context, category: str | None = None):
        """Diagnostic log_config. Option : +logsdiag messages pour faire aussi un test."""
        requested = (category or "").strip().casefold().replace("-", "_")
        if requested and requested not in log_service.LOG_TYPES:
            return await ctx.send(
                "Catégorie inconnue. Utilise : `" + ", ".join(log_service.LOG_TYPES) + "`."
            )

        rows = []
        for key in log_service.LOG_TYPES:
            if requested and key != requested:
                continue
            config = await log_service.get_log_config(self.bot, ctx.guild.id, key)
            setting = await log_service.get_log_setting(self.bot, ctx.guild.id, key)
            channel_id = setting.get("channel_id")
            channel = ctx.guild.get_channel(int(channel_id)) if channel_id else None
            ok, reason = log_service.validate_channel(ctx.guild, channel_id, needs_file=True)
            legacy = None
            try:
                legacy = await self.bot.db.fetchone(
                    "SELECT channel_id,enabled,updated_at FROM log_settings "
                    "WHERE guild_id=? AND log_type=?",
                    (ctx.guild.id, key),
                )
            except Exception:
                pass
            legacy_id = int(legacy["channel_id"]) if legacy and legacy["channel_id"] else None
            rows.append(
                f"{key}: enabled={int(bool((config or {}).get('enabled')))} "
                f"config={channel_id or '-'} legacy={legacy_id or '-'} "
                f"channel={'OK' if channel else 'ABSENT'} perms={'OK' if ok else reason}"
            )

        text = "LOGS DIAG — source runtime=log_config\n" + "\n".join(rows)
        if requested:
            sent, detail = await log_service.send_test_log(self.bot, ctx.guild, requested, ctx.author)
            text += f"\nTEST {requested}: {'OK' if sent else 'ECHEC'} — {detail}"
        # Discord limite un message à 2000 caractères.
        for start in range(0, len(text), 1900):
            await ctx.send(f"```text\n{text[start:start + 1900]}\n```")


async def _bootstrap(bot: commands.Bot) -> None:
    try:
        await bot.wait_until_ready()
    except RuntimeError:
        return
    await asyncio.sleep(2)
    _sanitize_catalog()
    await _install_setup_bridge(bot)
    recovered = await _reconcile_recent_setup_rows(bot)
    total = 0
    for guild in list(bot.guilds):
        total += await sync_generated_logs(bot, guild)
    if bot.get_cog("LogsDiagnostics") is None:
        await bot.add_cog(LogsDiagnostics(bot))
    logger.info(
        "Réconciliation logs terminée : %s route(s) générée(s), %s choix Setup récupéré(s).",
        total,
        recovered,
    )


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_generated_logs_reconciler", False):
        return
    bot._sentrix_generated_logs_reconciler = True
    _sanitize_catalog()
    asyncio.create_task(_bootstrap(bot), name="sentrix-generated-logs-reconcile")


__all__ = ["LOG_CHANNEL_ALIASES", "LogsDiagnostics", "install", "sync_generated_logs"]
