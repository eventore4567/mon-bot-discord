"""Synchronise les salons LOGS existants avec le moteur ``log_settings``.

Le bot a utilisé plusieurs conventions de noms au fil des versions. Le constructeur
historique, ``/create-logs`` et ``+create-server`` n'ont pas toujours créé exactement les
mêmes noms. Après une perte de base locale, cette couche peut redécouvrir les salons
SentriX existants. Elle ne doit en revanche jamais annuler un choix explicite fait dans
``+setup`` : un log déjà configuré puis désactivé reste désactivé.

Cette couche installe aussi la sauvegarde atomique des routes de logs. Le panneau Setup
ne doit jamais pouvoir afficher un salon sélectionné puis échouer avec
``ValueError: channel_required`` parce qu'une ligne ``log_config`` n'existait pas encore :
la sélection du salon fait désormais un UPSERT réel avant toute activation.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import re
import unicodedata

import discord
from discord.ext import commands

from utils import log_service

logger = logging.getLogger("bot.generated-logs-sync")

LOG_CHANNEL_ALIASES: dict[str, tuple[str, ...]] = {
    "messages": ("logs-messages", "logs-message"),
    "members": ("logs-membre", "logs-membres", "logs-member", "logs-members"),
    "voice": ("logs-vocal", "logs-vocaux", "logs-voice"),
    "roles": ("logs-roles", "logs-rôles", "logs-role", "logs-rôle"),
    "server": ("logs-salons", "logs-serveur", "logs-server"),
    # Compatibilité V6 : les anciens salons logs-dossiers/logs-fichiers restent rattachés
    # à la clé historique ``files``. Le nouveau salon ``logs-ressources`` utilise la clé
    # V2 ``resources`` afin de ne casser ni les anciens resets ni les nouveaux événements.
    "files": ("logs-dossiers", "logs-fichiers", "logs-files"),
    "resources": ("logs-ressources",),
    "moderation": ("logs-moderation", "logs-modération", "logs-modo"),
    "tickets": ("logs-tickets", "logs-ticket"),
    "automod": ("logs-securite", "logs-sécurité", "logs-automod", "logs-security"),
}


def _plain(value: str) -> str:
    value = (value or "").strip()
    if "・" in value:
        value = value.split("・", 1)[1]
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold().replace("_", " ")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value


_NORMALIZED_ALIASES = {
    log_type: frozenset(_plain(name) for name in aliases)
    for log_type, aliases in LOG_CHANNEL_ALIASES.items()
}


def _looks_like_log_category(channel: discord.TextChannel) -> bool:
    category = getattr(channel, "category", None)
    if category is None:
        return False
    name = _plain(getattr(category, "name", ""))
    return "logs" in name or ("sentrix" in name and "log" in name)


def _find_log_channel(guild: discord.Guild, log_type: str) -> discord.TextChannel | None:
    wanted = _NORMALIZED_ALIASES.get(log_type, frozenset())
    if not wanted:
        return None
    for channel in guild.text_channels:
        if _plain(channel.name) in wanted and _looks_like_log_category(channel):
            return channel
    for channel in guild.text_channels:
        if _plain(channel.name) in wanted:
            return channel
    return None


async def _explicitly_disabled(bot: commands.Bot, guild_id: int, log_type: str) -> bool:
    """Une route avec un salon choisi + enabled=0 est une désactivation volontaire.

    Les anciennes lignes de migration non configurées ont channel_id=NULL. Elles restent
    récupérables après perte de base, mais une route réellement configurée ne sera plus
    réactivée automatiquement au redémarrage.
    """
    row = await bot.db.fetchone(
        "SELECT enabled, channel_id FROM log_settings WHERE guild_id=? AND log_type=?",
        (guild_id, log_type),
    )
    return bool(row is not None and not bool(row["enabled"]) and row["channel_id"])


def _install_atomic_log_route_save() -> None:
    """Rend le choix de salon du Setup réellement persistant et atomique.

    L'ancien ``set_log_channel`` faisait d'abord ``_ensure_category_row`` puis un simple
    ``UPDATE``. Avec plusieurs générations de schéma/runtime, une ligne pouvait être
    absente ou migrée au mauvais moment : l'UPDATE touchait alors 0 ligne. Le menu Discord
    montrait pourtant la sélection locale, puis ``set_log_enabled(True)`` relisait une
    route sans salon et levait ``ValueError: channel_required``.

    On écrit maintenant la route avec ``INSERT .. ON CONFLICT DO UPDATE``. Une sélection
    non vide active aussi la route dans la même transaction logique ; le callback Setup
    peut ensuite rappeler ``set_log_enabled(True)`` sans course ni état intermédiaire.
    """
    current_set_channel = log_service.set_log_channel
    current_set_enabled = log_service.set_log_enabled

    if getattr(current_set_channel, "_sentrix_atomic_route_save", False):
        return

    @functools.wraps(current_set_channel)
    async def set_log_channel_atomic(
        bot: commands.Bot,
        guild_id: int,
        log_type: str,
        channel_id: int | None,
    ) -> dict:
        category, _emoji, _kind = log_service.resolve(log_type)
        await log_service._ensure_log_config_schema(bot)

        # Valide l'ID tôt pour éviter d'enregistrer une pseudo-valeur issue d'un composant.
        normalized_channel_id = int(channel_id) if channel_id is not None else None

        existing = await bot.db.fetchone(
            "SELECT enabled FROM log_config WHERE guild_id=? AND category=?",
            (int(guild_id), category),
        )
        previous_enabled = bool(existing["enabled"]) if existing is not None else True
        enabled = True if normalized_channel_id is not None else previous_enabled

        await bot.db.execute(
            "INSERT INTO log_config (guild_id,category,channel_id,enabled) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id,category) DO UPDATE SET "
            "channel_id=excluded.channel_id, "
            "enabled=CASE WHEN excluded.channel_id IS NOT NULL THEN 1 ELSE log_config.enabled END",
            (
                int(guild_id),
                category,
                normalized_channel_id,
                1 if enabled else 0,
            ),
        )

        # Garde les anciens écrans/modules synchronisés sans dépendre de leur schéma.
        try:
            await log_service._mirror_legacy_setting(
                bot,
                int(guild_id),
                category,
                channel_id=normalized_channel_id,
                enabled=bool(enabled),
            )
        except Exception:
            logger.debug(
                "Miroir legacy ignoré après sauvegarde atomique guild=%s type=%s",
                guild_id,
                category,
                exc_info=True,
            )

        saved = await log_service.get_log_setting(bot, int(guild_id), category)
        if normalized_channel_id is not None and int(saved.get("channel_id") or 0) != normalized_channel_id:
            # Ne jamais masquer une écriture qui n'aurait pas réellement persisté.
            raise RuntimeError("log_channel_not_persisted")
        return saved

    @functools.wraps(current_set_enabled)
    async def set_log_enabled_atomic(
        bot: commands.Bot,
        guild_id: int,
        log_type: str,
        enabled: bool,
    ) -> dict:
        category, _emoji, _kind = log_service.resolve(log_type)
        await log_service._ensure_log_config_schema(bot)

        row = await bot.db.fetchone(
            "SELECT channel_id,enabled FROM log_config WHERE guild_id=? AND category=?",
            (int(guild_id), category),
        )
        if row is None:
            # Crée la ligne canonique avant de modifier son état.
            await log_service._ensure_category_row(bot, int(guild_id), category)
            row = await bot.db.fetchone(
                "SELECT channel_id,enabled FROM log_config WHERE guild_id=? AND category=?",
                (int(guild_id), category),
            )

        dedicated_channel_id = int(row["channel_id"]) if row is not None and row["channel_id"] else None
        if enabled and dedicated_channel_id is None:
            raise ValueError("channel_required")

        await bot.db.execute(
            "INSERT INTO log_config (guild_id,category,channel_id,enabled) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id,category) DO UPDATE SET enabled=excluded.enabled",
            (
                int(guild_id),
                category,
                dedicated_channel_id,
                1 if enabled else 0,
            ),
        )
        try:
            await log_service._mirror_legacy_setting(
                bot,
                int(guild_id),
                category,
                channel_id=dedicated_channel_id,
                enabled=bool(enabled),
            )
        except Exception:
            logger.debug(
                "Miroir legacy ignoré après activation atomique guild=%s type=%s",
                guild_id,
                category,
                exc_info=True,
            )
        return await log_service.get_log_setting(bot, int(guild_id), category)

    set_log_channel_atomic._sentrix_atomic_route_save = True
    set_log_channel_atomic._sentrix_previous = current_set_channel
    set_log_enabled_atomic._sentrix_atomic_route_save = True
    set_log_enabled_atomic._sentrix_previous = current_set_enabled
    log_service.set_log_channel = set_log_channel_atomic
    log_service.set_log_enabled = set_log_enabled_atomic
    logger.info("Sauvegarde atomique des salons de logs installée.")


async def sync_generated_logs(bot: commands.Bot, guild: discord.Guild) -> int:
    """Redécouvre les routes manquantes sans écraser les désactivations explicites."""
    found: dict[str, discord.TextChannel] = {}
    for log_type in LOG_CHANNEL_ALIASES:
        channel = _find_log_channel(guild, log_type)
        if channel is not None:
            found[log_type] = channel

    if len(found) < 2:
        logger.info(
            "Auto-récupération logs ignorée guild=%s : seulement %s salon(s) SentriX reconnu(s).",
            guild.id,
            len(found),
        )
        return 0

    try:
        await bot.db.ensure_guild(guild.id)
    except Exception:
        logger.exception("Impossible de garantir guild_config avant resynchronisation guild=%s.", guild.id)

    synced = 0
    preserved = 0
    for log_type, channel in found.items():
        meta = log_service.LOG_TYPES.get(log_type, {})
        if not meta:
            # Une ancienne couche chargée avant Setup V2 peut ne pas encore connaître
            # ``resources``. On attend simplement que la couche V2 soit installée.
            if log_type == "resources":
                continue
        try:
            if await _explicitly_disabled(bot, guild.id, log_type):
                preserved += 1
                logger.info(
                    "Route log explicitement désactivée conservée guild=%s type=%s.",
                    guild.id,
                    log_type,
                )
                continue
            legacy_column = meta.get("legacy_column")
            if legacy_column:
                await bot.db.set_guild_config(guild.id, legacy_column, channel.id)
            await log_service.set_log_channel(bot, guild.id, log_type, channel.id)
            await log_service.set_log_enabled(bot, guild.id, log_type, True)
            synced += 1
        except Exception:
            logger.exception(
                "Resynchronisation impossible guild=%s type=%s channel=%s.",
                guild.id,
                log_type,
                channel.id,
            )

    moderation = found.get("moderation")
    if moderation is not None:
        try:
            if not await _explicitly_disabled(bot, guild.id, "moderation"):
                await bot.db.set_guild_config(guild.id, "log_channel", moderation.id)
        except Exception:
            logger.exception("Impossible de restaurer log_channel guild=%s.", guild.id)

    logger.warning(
        "Logs SentriX auto-récupérés guild=%s : %s/%s route(s) actives, %s désactivation(s) conservée(s).",
        guild.id,
        synced,
        len(found),
        preserved,
    )
    return synced


async def _bootstrap(bot: commands.Bot) -> None:
    try:
        await bot.wait_until_ready()
    except RuntimeError:
        return
    await asyncio.sleep(4)
    for guild in list(bot.guilds):
        try:
            await sync_generated_logs(bot, guild)
        except Exception:
            logger.exception("Synchronisation des logs impossible sur %s (%s).", guild.name, guild.id)


def install(bot: commands.Bot) -> None:
    from . import server_builder

    # Cette fonction est appelée tôt par cogs.__init__, avant l'ouverture du Setup.
    # Le patch reste donc actif pour tous les callbacks de sélection de salon.
    _install_atomic_log_route_save()

    original = server_builder.ServerBuilder._configure_bot_channels
    if not getattr(original, "_sentrix_log_settings_sync", False):
        async def configure_with_log_sync(self, guild, role_map, category_map, channel_map, staff_role_name):
            result = await original(self, guild, role_map, category_map, channel_map, staff_role_name)
            await sync_generated_logs(self.bot, guild)
            return result

        configure_with_log_sync._sentrix_log_settings_sync = True
        server_builder.ServerBuilder._configure_bot_channels = configure_with_log_sync

    if getattr(bot, "_sentrix_generated_logs_sync_installed", False):
        return
    bot._sentrix_generated_logs_sync_installed = True
    asyncio.create_task(_bootstrap(bot), name="sentrix-generated-logs-sync")
    logger.info("Synchronisation LOGS SentriX activée avec conservation des désactivations explicites.")