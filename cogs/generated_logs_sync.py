"""Réconciliation légère et diagnostic des salons de logs SentriX.

Le runtime lit uniquement ``log_config``. L'ancien écran +setup écrit encore dans
``log_config``, écrite via ``log_service.set_log_config``. Ce module ne fait plus que
créer les salons manquants et exposer ``+logsdiag``.
"""
from __future__ import annotations

import asyncio
import logging
import re
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
    "resources": ("logs-resources", "logs-ressources", "logs-invitations"),
    "files": ("logs-dossiers", "logs-fichiers", "logs-files"),
}

_CANONICAL = tuple(LOG_CHANNEL_ALIASES)


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


# _install_setup_bridge et _reconcile_recent_setup_rows SUPPRIMÉS.
#
# Ils installaient deux triggers SQL sur log_settings pour répercuter les écritures du
# vieux +setup vers log_config. Deux autres triggers faisaient la même chose depuis
# log_service, avec un mapping différent (ELSE 'server') : toute valeur non reconnue
# écrasait donc silencieusement la route de la catégorie "server". log_settings est
# désormais migrée puis archivée une seule fois par Database._migrate_logs(), et le
# +setup écrit directement dans log_config via log_service.set_log_config.


async def _explicitly_disabled(bot: commands.Bot, guild_id: int, category: str) -> bool:
    """Une route désactivée AVEC salon est un choix explicite : on ne la réactive jamais.

    Une route désactivée SANS salon n'a jamais été configurée : la synchronisation peut
    donc l'alimenter avec un salon nommé logs-* trouvé sur le serveur.
    """
    row = await bot.db.fetchone(
        "SELECT enabled, channel_id FROM log_config WHERE guild_id = ? AND category = ?",
        (int(guild_id), str(category)),
    )
    if row is None:
        return False
    return not bool(row["enabled"]) and bool(row["channel_id"])


async def sync_generated_logs(bot: commands.Bot, guild: discord.Guild) -> int:
    _sanitize_catalog()
    changed = 0
    for category in tuple(log_service.LOG_TYPES):
        try:
            config = await log_service.get_log_config(bot, guild.id, category)
        except Exception:
            logger.exception("Lecture log_config impossible guild=%s category=%s", guild.id, category)
            continue
        if config is None or config.get("channel_id"):
            continue
        if not config.get("enabled") and await _explicitly_disabled(bot, guild.id, category):
            continue
        if not config.get("enabled"):
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

    async def _send_diag(
        self,
        destination,
        guild: discord.Guild,
        author: discord.Member,
        category: str = "",
    ) -> None:
        requested = (category or "").strip().casefold().replace("-", "_")
        if requested and requested not in log_service.LOG_TYPES:
            await destination.send(
                "Catégorie inconnue. Utilise : `" + ", ".join(log_service.LOG_TYPES) + "`."
            )
            return

        rows: list[str] = []
        keys = [requested] if requested else list(log_service.LOG_TYPES)
        for key in keys:
            try:
                config = await log_service.get_log_config(self.bot, guild.id, key)
                channel_id = (config or {}).get("channel_id")
                channel = guild.get_channel(int(channel_id)) if channel_id else None
                ok, reason = log_service.validate_channel(
                    guild, channel_id, needs_file=True
                )
                rows.append(
                    f"{key}: enabled={int(bool((config or {}).get('enabled')))} "
                    f"config={channel_id or '-'} "
                    f"updated_at={(config or {}).get('updated_at') or '-'} "
                    f"channel={'OK' if channel else 'ABSENT'} "
                    f"perms={'OK' if ok else reason}"
                )
            except Exception as exc:
                logger.exception(
                    "logsdiag route échouée guild=%s category=%s",
                    guild.id,
                    key,
                )
                rows.append(
                    f"{key}: ROUTE_ERROR {type(exc).__name__}: {str(exc)[:300]}"
                )

        text = "LOGS DIAG — source runtime=log_config\n" + "\n".join(rows)
        for start in range(0, len(text), 1850):
            await destination.send(f"```text\n{text[start:start + 1850]}\n```")

        if requested:
            try:
                sent, detail = await log_service.send_test_log(
                    self.bot, guild, requested, author
                )
                await destination.send(
                    f"```text\nTEST {requested}: {'OK' if sent else 'ECHEC'} — {detail[:1500]}\n```"
                )
            except Exception as exc:
                logger.exception(
                    "logsdiag test échoué guild=%s category=%s",
                    guild.id,
                    requested,
                )
                await destination.send(
                    "```text\n"
                    f"TEST {requested}: EXCEPTION {type(exc).__name__}: {str(exc)[:1500]}\n"
                    "```"
                )

    @commands.command(name="logsdiag")
    @commands.guild_only()
    async def logsdiag(self, ctx: commands.Context, category: str = ""):
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            return
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("Cette commande est réservée aux administrateurs du serveur.")
        await self._send_diag(ctx.channel, ctx.guild, ctx.author, category)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Diagnostic hors moteur de commandes : écrire `logsdiag messages` sans préfixe."""
        if message.author.bot or message.guild is None:
            return
        raw = (message.content or "").strip()
        lowered = raw.casefold()
        if lowered != "logsdiag" and not lowered.startswith("logsdiag "):
            return
        if not isinstance(message.author, discord.Member):
            return
        if not message.author.guild_permissions.administrator:
            await message.channel.send("Ce diagnostic est réservé aux administrateurs du serveur.")
            return
        parts = raw.split(maxsplit=1)
        category = parts[1] if len(parts) > 1 else ""
        try:
            await self._send_diag(message.channel, message.guild, message.author, category)
        except Exception as exc:
            logger.exception("logsdiag hors commande a échoué guild=%s", message.guild.id)
            await message.channel.send(
                "```text\n"
                f"LOGSDIAG FATAL {type(exc).__name__}: {str(exc)[:1500]}\n"
                "```"
            )


async def _bootstrap(bot: commands.Bot) -> None:
    try:
        await bot.wait_until_ready()
    except RuntimeError:
        return
    await asyncio.sleep(2)
    _sanitize_catalog()
    total = 0
    for guild in list(bot.guilds):
        total += await sync_generated_logs(bot, guild)
    if bot.get_cog("LogsDiagnostics") is None:
        await bot.add_cog(LogsDiagnostics(bot))
    logger.info("Réconciliation logs terminée : %s route(s) générée(s).", total)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_generated_logs_reconciler", False):
        return
    bot._sentrix_generated_logs_reconciler = True
    _sanitize_catalog()
    asyncio.create_task(_bootstrap(bot), name="sentrix-generated-logs-reconcile")


__all__ = ["LOG_CHANNEL_ALIASES", "LogsDiagnostics", "_explicitly_disabled", "install", "sync_generated_logs"]
