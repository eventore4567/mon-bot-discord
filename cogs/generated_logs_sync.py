"""Synchronise les salons de logs générés avec le routeur canonique SentriX.

Cette couche a deux rôles :
- redécouvrir les salons de logs existants après un redémarrage/perte de cache ;
- garantir que TOUT le panneau +setup Logs écrit dans ``log_config`` via
  ``utils.log_service`` au lieu de modifier directement l'ancienne table ``log_settings``.

Ainsi une sélection de salon ne peut plus être visible dans Discord sans être réellement
persistée, et ``ValueError: channel_required`` ne peut plus apparaître après avoir choisi
un salon.
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


# Toutes les routes connues, anciennes et nouvelles. Important : ``logs-salons`` n'est
# jamais un alias de ``server`` ; Salons et Serveur sont deux catégories distinctes.
LOG_CHANNEL_ALIASES: dict[str, tuple[str, ...]] = {
    "messages": ("logs-messages", "logs-message"),
    "members": ("logs-membre", "logs-membres", "logs-member", "logs-members"),
    "channels": ("logs-salons", "logs-channels", "logs-channel"),
    "roles": ("logs-roles", "logs-rôles", "logs-role", "logs-rôle"),
    "voice": ("logs-vocal", "logs-vocaux", "logs-voice"),
    "server": ("logs-serveur", "logs-server"),
    "moderation": ("logs-moderation", "logs-modération", "logs-modo"),
    "tickets": ("logs-tickets", "logs-ticket"),
    "dossiers": ("logs-dossiers", "logs-invitations"),
    "spam": ("logs-protect-spam-logs", "logs-spam", "protect-spam-logs"),
    "automod": ("automod", "logs-securite", "logs-sécurité", "logs-automod", "logs-security"),
    "raid": ("raidprotect-logs", "logs-raid", "raid-protect-logs"),
    # Compatibilité avec les anciennes versions qui avaient deux routes ressources/fichiers.
    "files": ("logs-fichiers", "logs-files"),
    "resources": ("logs-ressources",),
}


def _plain(value: str) -> str:
    value = (value or "").strip()
    if "・" in value:
        value = value.split("・", 1)[1]
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold().replace("_", " ")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


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
    # Priorité à la catégorie de logs pour éviter un salon homonyme ailleurs.
    for channel in guild.text_channels:
        if _plain(channel.name) in wanted and _looks_like_log_category(channel):
            return channel
    for channel in guild.text_channels:
        if _plain(channel.name) in wanted:
            return channel
    return None


async def _explicitly_disabled(bot: commands.Bot, guild_id: int, log_type: str) -> bool:
    """Une route historique avec salon + enabled=0 est une désactivation volontaire."""
    try:
        row = await bot.db.fetchone(
            "SELECT enabled, channel_id FROM log_settings WHERE guild_id=? AND log_type=?",
            (guild_id, log_type),
        )
    except Exception:
        return False
    return bool(row is not None and not bool(row["enabled"]) and row["channel_id"])


def _install_atomic_log_route_save() -> None:
    """Rend set_log_channel/set_log_enabled atomiques dans la table canonique."""
    current_set_channel = log_service.set_log_channel
    current_set_enabled = log_service.set_log_enabled

    if getattr(current_set_channel, "_sentrix_atomic_route_save_v2", False):
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
        if (
            normalized_channel_id is not None
            and int(saved.get("channel_id") or 0) != normalized_channel_id
        ):
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
            await log_service._ensure_category_row(bot, int(guild_id), category)
            row = await bot.db.fetchone(
                "SELECT channel_id,enabled FROM log_config WHERE guild_id=? AND category=?",
                (int(guild_id), category),
            )

        dedicated_channel_id = (
            int(row["channel_id"])
            if row is not None and row["channel_id"]
            else None
        )
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

    set_log_channel_atomic._sentrix_atomic_route_save_v2 = True
    set_log_channel_atomic._sentrix_previous = current_set_channel
    set_log_enabled_atomic._sentrix_atomic_route_save_v2 = True
    set_log_enabled_atomic._sentrix_previous = current_set_enabled
    log_service.set_log_channel = set_log_channel_atomic
    log_service.set_log_enabled = set_log_enabled_atomic
    logger.info("Sauvegarde atomique V2 des salons de logs installée.")


async def _mirror_exact_setup_setting(
    bot: commands.Bot,
    guild_id: int,
    log_type: str,
    channel_id: int | None,
    enabled: bool,
) -> None:
    """Maintient l'ancienne table lisible sans qu'elle soit la source de vérité."""
    try:
        await bot.db.execute(
            "INSERT INTO log_settings "
            "(guild_id,log_type,enabled,channel_id,include_content,include_attachments,"
            "include_actor,include_reason,created_at,updated_at) "
            "VALUES (?,?,?,?,1,1,1,1,strftime('%s','now'),strftime('%s','now')) "
            "ON CONFLICT(guild_id,log_type) DO UPDATE SET "
            "enabled=excluded.enabled,channel_id=excluded.channel_id,"
            "updated_at=excluded.updated_at",
            (
                int(guild_id),
                str(log_type),
                1 if enabled else 0,
                int(channel_id) if channel_id is not None else None,
            ),
        )
    except Exception:
        # Certains très anciens schémas n'ont pas toutes les colonnes optionnelles.
        try:
            await bot.db.execute(
                "INSERT INTO log_settings (guild_id,log_type,enabled,channel_id) "
                "VALUES (?,?,?,?) "
                "ON CONFLICT(guild_id,log_type) DO UPDATE SET "
                "enabled=excluded.enabled,channel_id=excluded.channel_id",
                (
                    int(guild_id),
                    str(log_type),
                    1 if enabled else 0,
                    int(channel_id) if channel_id is not None else None,
                ),
            )
        except Exception:
            logger.debug(
                "Miroir exact log_settings indisponible guild=%s type=%s",
                guild_id,
                log_type,
                exc_info=True,
            )


async def _save_setup_log_route(
    owner,
    log_type: str,
    channel_id: int | None,
) -> dict:
    """Sauvegarde une sélection du +setup pour n'importe quelle catégorie de log."""
    guild_id = int(owner.guild.id)

    if channel_id is None:
        # Désactiver AVANT de retirer le salon évite toute tentative d'activer une route vide.
        try:
            await log_service.set_log_enabled(owner.bot, guild_id, log_type, False)
        except ValueError:
            pass
        saved = await log_service.set_log_channel(owner.bot, guild_id, log_type, None)
        await _mirror_exact_setup_setting(owner.bot, guild_id, log_type, None, False)
        return saved

    channel_id = int(channel_id)
    channel = owner.guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("invalid_log_channel")

    # Une sélection non vide signifie : cette catégorie doit réellement utiliser ce salon.
    await log_service.set_log_channel(owner.bot, guild_id, log_type, channel_id)
    saved = await log_service.set_log_enabled(owner.bot, guild_id, log_type, True)
    await _mirror_exact_setup_setting(owner.bot, guild_id, log_type, channel_id, True)

    persisted = int(saved.get("channel_id") or 0)
    if persisted != channel_id:
        raise RuntimeError("log_channel_not_persisted")
    return saved


async def _legacy_channel_for_toggle(owner, log_type: str) -> int | None:
    """Récupère une ancienne sélection avant d'afficher une erreur 'salon requis'."""
    try:
        row = await owner.bot.db.fetchone(
            "SELECT channel_id FROM log_settings WHERE guild_id=? AND log_type=?",
            (owner.guild.id, log_type),
        )
    except Exception:
        return None
    if row is None or not row["channel_id"]:
        return None
    channel_id = int(row["channel_id"])
    return channel_id if owner.guild.get_channel(channel_id) is not None else None


def _install_setup_log_callbacks() -> None:
    """Force tous les contrôles Logs du +setup à passer par log_service."""
    try:
        from . import setup_control_center as setup_ui
    except Exception:
        logger.exception("Impossible d'installer les callbacks canoniques du Setup Logs.")
        return

    # 1) Sélecteur de salon : ce callback est commun à TOUTES les catégories.
    current_channel_callback = setup_ui.LogChannelSelect.callback
    if not getattr(current_channel_callback, "_sentrix_all_logs_canonical", False):

        async def canonical_channel_callback(self, interaction: discord.Interaction):
            log_type = self.owner.selected_log
            if not log_type:
                return await interaction.response.send_message(
                    "Choisissez d'abord une catégorie de logs.",
                    ephemeral=True,
                )

            channel_id = int(self.values[0].id) if self.values else None
            await _save_setup_log_route(self.owner, log_type, channel_id)
            await self.owner.audit(interaction.user.id, log_type, channel_id)
            await self.owner.refresh(interaction)

        canonical_channel_callback._sentrix_all_logs_canonical = True
        canonical_channel_callback._sentrix_previous = current_channel_callback
        setup_ui.LogChannelSelect.callback = canonical_channel_callback

    # 2) Le bouton d'activation est une closure recréée par SetupView.render().
    # On enveloppe donc render() et on remplace ce callback après chaque rendu.
    current_render = setup_ui.SetupView.render
    if getattr(current_render, "_sentrix_all_logs_toggle", False):
        return

    @functools.wraps(current_render)
    def render_with_canonical_log_toggle(self):
        result = current_render(self)

        if self.category != "logs" or not self.selected_log:
            return result

        for item in list(self.children):
            if not isinstance(item, discord.ui.Button):
                continue
            label = (item.label or "").casefold()
            if "log" not in label or not ("activer" in label or "désactiver" in label):
                continue
            if getattr(item.callback, "_sentrix_all_logs_canonical", False):
                continue

            async def canonical_toggle(
                interaction: discord.Interaction,
                owner=self,
            ):
                log_type = owner.selected_log
                if not log_type:
                    return await interaction.response.send_message(
                        "Choisissez d'abord une catégorie de logs.",
                        ephemeral=True,
                    )

                setting = await log_service.get_log_setting(
                    owner.bot,
                    owner.guild.id,
                    log_type,
                )
                target_enabled = not bool(setting.get("enabled"))
                channel_id = (
                    int(setting["channel_id"])
                    if setting.get("channel_id")
                    else None
                )

                if target_enabled and channel_id is None:
                    # Répare d'abord une éventuelle sélection provenant d'une ancienne table.
                    channel_id = await _legacy_channel_for_toggle(owner, log_type)
                    if channel_id is None:
                        discovered = _find_log_channel(owner.guild, log_type)
                        channel_id = discovered.id if discovered is not None else None
                    if channel_id is None:
                        return await interaction.response.send_message(
                            "Choisissez d'abord le salon de cette catégorie de logs.",
                            ephemeral=True,
                        )
                    await log_service.set_log_channel(
                        owner.bot,
                        owner.guild.id,
                        log_type,
                        channel_id,
                    )

                saved = await log_service.set_log_enabled(
                    owner.bot,
                    owner.guild.id,
                    log_type,
                    target_enabled,
                )
                final_channel_id = (
                    int(saved["channel_id"])
                    if saved.get("channel_id")
                    else channel_id
                )
                await _mirror_exact_setup_setting(
                    owner.bot,
                    owner.guild.id,
                    log_type,
                    final_channel_id,
                    target_enabled,
                )
                await owner.audit(
                    interaction.user.id,
                    f"{log_type}:enabled",
                    int(target_enabled),
                )
                await owner.refresh(interaction)

            canonical_toggle._sentrix_all_logs_canonical = True
            item.callback = canonical_toggle

        return result

    render_with_canonical_log_toggle._sentrix_all_logs_toggle = True
    render_with_canonical_log_toggle._sentrix_previous = current_render
    setup_ui.SetupView.render = render_with_canonical_log_toggle
    logger.info("Callbacks +setup Logs canoniques installés pour toutes les catégories.")


async def sync_generated_logs(bot: commands.Bot, guild: discord.Guild) -> int:
    """Redécouvre les routes manquantes sans écraser les désactivations explicites."""
    found: dict[str, discord.TextChannel] = {}
    for log_type in LOG_CHANNEL_ALIASES:
        channel = _find_log_channel(guild, log_type)
        if channel is not None:
            found[log_type] = channel

    if len(found) < 2:
        logger.info(
            "Auto-récupération logs ignorée guild=%s : seulement %s salon(s) reconnu(s).",
            guild.id,
            len(found),
        )
        return 0

    try:
        await bot.db.ensure_guild(guild.id)
    except Exception:
        logger.exception(
            "Impossible de garantir guild_config avant resynchronisation guild=%s.",
            guild.id,
        )

    synced = 0
    preserved = 0
    for log_type, channel in found.items():
        meta = log_service.LOG_TYPES.get(log_type)
        # Les catégories V3 sont présentes après READY. Si un runtime ne les connaît pas,
        # on ne les rabat surtout pas sur 'server'.
        if not meta:
            continue
        if not meta.get("emits", True):
            continue

        try:
            if await _explicitly_disabled(bot, guild.id, log_type):
                preserved += 1
                continue

            legacy_column = meta.get("legacy_column")
            if legacy_column:
                await bot.db.set_guild_config(guild.id, legacy_column, channel.id)

            await log_service.set_log_channel(bot, guild.id, log_type, channel.id)
            await log_service.set_log_enabled(bot, guild.id, log_type, True)
            await _mirror_exact_setup_setting(
                bot,
                guild.id,
                log_type,
                channel.id,
                True,
            )
            synced += 1
        except Exception:
            logger.exception(
                "Resynchronisation impossible guild=%s type=%s channel=%s.",
                guild.id,
                log_type,
                channel.id,
            )

    logger.warning(
        "Logs SentriX auto-récupérés guild=%s : %s/%s route(s) actives, "
        "%s désactivation(s) conservée(s).",
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

    # Les couches V73/V74/V3 peuvent avoir remplacé des callbacks pendant le chargement.
    # On réaffirme donc la version canonique une fois le runtime final prêt.
    _install_atomic_log_route_save()
    _install_setup_log_callbacks()

    await asyncio.sleep(4)
    for guild in list(bot.guilds):
        try:
            await sync_generated_logs(bot, guild)
        except Exception:
            logger.exception(
                "Synchronisation des logs impossible sur %s (%s).",
                guild.name,
                guild.id,
            )


def install(bot: commands.Bot) -> None:
    from . import server_builder

    _install_atomic_log_route_save()
    _install_setup_log_callbacks()

    original = server_builder.ServerBuilder._configure_bot_channels
    if not getattr(original, "_sentrix_log_settings_sync", False):

        async def configure_with_log_sync(
            self,
            guild,
            role_map,
            category_map,
            channel_map,
            staff_role_name,
        ):
            result = await original(
                self,
                guild,
                role_map,
                category_map,
                channel_map,
                staff_role_name,
            )
            await sync_generated_logs(self.bot, guild)
            return result

        configure_with_log_sync._sentrix_log_settings_sync = True
        server_builder.ServerBuilder._configure_bot_channels = configure_with_log_sync

    if getattr(bot, "_sentrix_generated_logs_sync_installed_v2", False):
        return
    bot._sentrix_generated_logs_sync_installed_v2 = True
    asyncio.create_task(_bootstrap(bot), name="sentrix-generated-logs-sync-v2")
    logger.info(
        "Synchronisation LOGS V2 activée : toutes les catégories utilisent log_config."
    )
