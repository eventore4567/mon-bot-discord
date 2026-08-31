"""Compatibilité et synchronisation des salons de logs SentriX.

Cette couche maintient le panneau +setup sur le routeur canonique ``log_config`` tout en
préservant les serveurs configurés avant la migration. Une route canonique vide peut être
réhydratée depuis ``log_settings`` ou ``guild_config`` ; une désactivation explicite avec
salon vidé n'est jamais réactivée automatiquement.
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


# Les clés sont CANONIQUES. Les anciens noms ne servent qu'à reconnaître les salons.
LOG_CHANNEL_ALIASES: dict[str, tuple[str, ...]] = {
    "messages": ("logs-messages", "logs-message"),
    "members": ("logs-membre", "logs-membres", "logs-member", "logs-members"),
    "channels": ("logs-salons", "logs-channels", "logs-channel"),
    "roles": ("logs-roles", "logs-rôles", "logs-role", "logs-rôle"),
    "voice": ("logs-vocal", "logs-vocaux", "logs-voice"),
    "server": ("logs-serveur", "logs-server"),
    "moderation": ("logs-moderation", "logs-modération", "logs-modo"),
    "tickets": ("logs-tickets", "logs-ticket"),
    "protection": (
        "automod",
        "logs-securite",
        "logs-sécurité",
        "logs-automod",
        "logs-security",
        "logs-protect-spam-logs",
        "logs-spam",
        "protect-spam-logs",
        "raidprotect-logs",
        "logs-raid",
        "raid-protect-logs",
    ),
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


def _find_log_channel(guild: discord.Guild, log_type: str) -> discord.TextChannel | None:
    wanted = _NORMALIZED_ALIASES.get(log_type, frozenset())
    if not wanted:
        return None

    # Priorité aux salons placés dans une catégorie de logs.
    for channel in guild.text_channels:
        category = getattr(channel, "category", None)
        category_name = _plain(getattr(category, "name", "")) if category else ""
        if (
            _plain(channel.name) in wanted
            and ("logs" in category_name or ("sentrix" in category_name and "log" in category_name))
        ):
            return channel

    for channel in guild.text_channels:
        if _plain(channel.name) in wanted:
            return channel
    return None


async def _legacy_candidate(
    bot: commands.Bot,
    guild_id: int,
    category: str,
) -> tuple[int | None, bool | None, str | None]:
    """Retourne l'ancienne route sans écraser une suppression explicite.

    ``log_settings`` est prioritaire. Une ligne désactivée sans salon correspond au nouvel
    état produit par +setup quand l'utilisateur retire volontairement une route : dans ce
    cas on ne retombe surtout pas sur une vieille colonne de ``guild_config``.
    """
    try:
        channel_id, enabled = await log_service._legacy_log_settings(
            bot,
            int(guild_id),
            category,
        )
    except Exception:
        channel_id, enabled = None, None

    if channel_id is not None:
        return int(channel_id), enabled, "log_settings"

    # Une ligne explicitement désactivée et vidée protège contre la résurrection d'une
    # ancienne valeur guild_config encore présente.
    if enabled is False:
        return None, False, "explicit_clear"

    try:
        channel_id = await log_service._legacy_channel_id(
            bot,
            int(guild_id),
            category,
        )
    except Exception:
        channel_id = None

    if channel_id is not None:
        return int(channel_id), enabled, "guild_config"
    return None, enabled, None


async def _explicitly_disabled(
    bot: commands.Bot,
    guild_id: int,
    log_type: str,
) -> bool:
    """Indique qu'une ancienne configuration demande réellement l'état désactivé."""
    try:
        category, _emoji, _kind = log_service.resolve(log_type)
        _channel_id, enabled, source = await _legacy_candidate(
            bot,
            int(guild_id),
            category,
        )
    except Exception:
        return False
    return bool(enabled is False and source in {"log_settings", "explicit_clear"})


def _install_legacy_route_repair() -> None:
    """Répare les lignes ``log_config`` vides créées avant la migration complète.

    Ancienne régression : ``_ensure_category_row`` retournait immédiatement une ligne
    existante, même si ``channel_id`` était NULL. Les anciennes valeurs de ``log_settings``
    et ``guild_config`` n'étaient donc plus consultées. Ici on ne remplit qu'une route vide
    lorsqu'une vraie ancienne route existe encore.
    """
    current = log_service._ensure_category_row
    if getattr(current, "_sentrix_legacy_route_repair_v84", False):
        return

    @functools.wraps(current)
    async def ensure_category_row_compat(
        bot: commands.Bot,
        guild_id: int,
        category: str,
    ):
        canonical, _emoji, _kind = log_service.resolve(category)
        row = await current(bot, int(guild_id), canonical)
        row_dict = dict(row)

        if row_dict.get("channel_id"):
            return row_dict

        legacy_channel, legacy_enabled, source = await _legacy_candidate(
            bot,
            int(guild_id),
            canonical,
        )
        if legacy_channel is None:
            return row_dict

        # Si l'ancienne ligne porte un état explicite, on le conserve. Sinon on garde
        # l'état canonique déjà présent.
        enabled = (
            bool(legacy_enabled)
            if legacy_enabled is not None
            else bool(row_dict.get("enabled", 1))
        )

        await bot.db.execute(
            "UPDATE log_config SET channel_id=?, enabled=? "
            "WHERE guild_id=? AND category=? AND channel_id IS NULL",
            (
                int(legacy_channel),
                1 if enabled else 0,
                int(guild_id),
                canonical,
            ),
        )
        repaired = await bot.db.fetchone(
            "SELECT guild_id,category,channel_id,enabled FROM log_config "
            "WHERE guild_id=? AND category=?",
            (int(guild_id), canonical),
        )
        if repaired is None:
            return row_dict

        logger.warning(
            "Route log legacy restaurée guild=%s type=%s channel=%s enabled=%s source=%s",
            guild_id,
            canonical,
            legacy_channel,
            enabled,
            source,
        )
        return dict(repaired)

    ensure_category_row_compat._sentrix_legacy_route_repair_v84 = True
    ensure_category_row_compat._sentrix_previous = current
    log_service._ensure_category_row = ensure_category_row_compat
    logger.info("Compatibilité des anciennes routes log_config installée.")


def _install_legacy_router_aliases() -> None:
    """Corrige les noms historiques avant que V83 ne vérifie LOG_TYPES."""
    try:
        from . import logs as logs_cog
    except Exception:
        logger.exception("Impossible de corriger les aliases du routeur Logs.")
        return

    # log_server est historiquement la colonne des événements de salons.
    logs_cog.CONFIG_TO_LOG_TYPE["log_server"] = "channels"
    # V83 refuse un type non canonique avant d'appeler resolve(); il faut donc fournir
    # directement la clé canonique.
    logs_cog.CONFIG_TO_LOG_TYPE["log_automod"] = "protection"
    logger.info("Aliases logs legacy corrigés : log_server->channels, log_automod->protection.")


def _install_atomic_log_route_save() -> None:
    """Rend set_log_channel/set_log_enabled atomiques dans la table canonique."""
    current_set_channel = log_service.set_log_channel
    current_set_enabled = log_service.set_log_enabled

    if getattr(current_set_channel, "_sentrix_atomic_route_save_v84", False):
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
        # Garantit que les anciennes routes ont eu une chance d'être récupérées avant
        # toute nouvelle écriture.
        await log_service._ensure_category_row(bot, int(guild_id), category)

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
                "Miroir legacy ignoré après sauvegarde guild=%s type=%s",
                guild_id,
                category,
                exc_info=True,
            )

        saved = await log_service.get_log_setting(bot, int(guild_id), category)
        if (
            normalized_channel_id is not None
            and int(saved.get("dedicated_channel_id") or 0) != normalized_channel_id
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

        # Le transport accepte le salon général comme repli. L'activation doit donc
        # suivre la même règle et ne pas exiger artificiellement un salon dédié.
        if enabled and dedicated_channel_id is None:
            try:
                effective = await log_service.get_log_setting(
                    bot,
                    int(guild_id),
                    category,
                )
            except Exception:
                effective = {}
            if not effective.get("channel_id"):
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
                "Miroir legacy ignoré après activation guild=%s type=%s",
                guild_id,
                category,
                exc_info=True,
            )
        return await log_service.get_log_setting(bot, int(guild_id), category)

    set_log_channel_atomic._sentrix_atomic_route_save_v84 = True
    set_log_channel_atomic._sentrix_previous = current_set_channel
    set_log_enabled_atomic._sentrix_atomic_route_save_v84 = True
    set_log_enabled_atomic._sentrix_previous = current_set_enabled
    log_service.set_log_channel = set_log_channel_atomic
    log_service.set_log_enabled = set_log_enabled_atomic
    logger.info("Sauvegarde atomique V84 des salons de logs installée.")


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
        # Désactivation AVANT suppression : l'état vide devient un marqueur explicite et
        # ne sera jamais réhydraté depuis guild_config au prochain redémarrage.
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

    await log_service.set_log_channel(owner.bot, guild_id, log_type, channel_id)
    saved = await log_service.set_log_enabled(owner.bot, guild_id, log_type, True)
    await _mirror_exact_setup_setting(owner.bot, guild_id, log_type, channel_id, True)

    persisted = int(saved.get("dedicated_channel_id") or 0)
    if persisted != channel_id:
        raise RuntimeError("log_channel_not_persisted")
    return saved


async def _legacy_channel_for_toggle(owner, log_type: str) -> int | None:
    try:
        category, _emoji, _kind = log_service.resolve(log_type)
        channel_id, _enabled, _source = await _legacy_candidate(
            owner.bot,
            owner.guild.id,
            category,
        )
    except Exception:
        return None

    if channel_id is None:
        return None
    return int(channel_id) if owner.guild.get_channel(int(channel_id)) is not None else None


def _install_setup_log_callbacks() -> None:
    """Force tous les contrôles Logs du +setup à passer par log_service."""
    try:
        from . import setup_control_center as setup_ui
    except Exception:
        logger.exception("Impossible d'installer les callbacks canoniques du Setup Logs.")
        return

    current_channel_callback = setup_ui.LogChannelSelect.callback
    if not getattr(current_channel_callback, "_sentrix_all_logs_canonical_v84", False):

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

        canonical_channel_callback._sentrix_all_logs_canonical_v84 = True
        canonical_channel_callback._sentrix_previous = current_channel_callback
        setup_ui.LogChannelSelect.callback = canonical_channel_callback

    current_render = setup_ui.SetupView.render
    if getattr(current_render, "_sentrix_all_logs_toggle_v84", False):
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
            if getattr(item.callback, "_sentrix_all_logs_canonical_v84", False):
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
                    int(setting["dedicated_channel_id"])
                    if setting.get("dedicated_channel_id")
                    else None
                )

                if target_enabled and channel_id is None:
                    channel_id = await _legacy_channel_for_toggle(owner, log_type)
                    if channel_id is None:
                        discovered = _find_log_channel(owner.guild, log_type)
                        channel_id = discovered.id if discovered is not None else None

                    # Si aucun salon dédié n'existe mais que le repli général est valide,
                    # set_log_enabled l'accepte maintenant.
                    if channel_id is not None:
                        await log_service.set_log_channel(
                            owner.bot,
                            owner.guild.id,
                            log_type,
                            channel_id,
                        )

                try:
                    saved = await log_service.set_log_enabled(
                        owner.bot,
                        owner.guild.id,
                        log_type,
                        target_enabled,
                    )
                except ValueError:
                    return await interaction.response.send_message(
                        "Choisissez d'abord le salon de cette catégorie de logs.",
                        ephemeral=True,
                    )

                final_channel_id = (
                    int(saved["dedicated_channel_id"])
                    if saved.get("dedicated_channel_id")
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

            canonical_toggle._sentrix_all_logs_canonical_v84 = True
            item.callback = canonical_toggle

        return result

    render_with_canonical_log_toggle._sentrix_all_logs_toggle_v84 = True
    render_with_canonical_log_toggle._sentrix_previous = current_render
    setup_ui.SetupView.render = render_with_canonical_log_toggle
    logger.info("Callbacks +setup Logs V84 installés pour toutes les catégories.")


async def repair_legacy_routes(bot: commands.Bot, guild: discord.Guild) -> int:
    """Réhydrate les routes des serveurs déjà configurés, sans modifier les clears."""
    repaired = 0
    await log_service._ensure_log_config_schema(bot)

    for category in log_service.LOG_TYPES:
        before = await bot.db.fetchone(
            "SELECT channel_id,enabled FROM log_config WHERE guild_id=? AND category=?",
            (guild.id, category),
        )
        before_channel = (
            int(before["channel_id"])
            if before is not None and before["channel_id"]
            else None
        )

        row = await log_service._ensure_category_row(bot, guild.id, category)
        after_channel = int(row["channel_id"]) if row.get("channel_id") else None
        if before_channel is None and after_channel is not None:
            repaired += 1

    if repaired:
        logger.warning(
            "Compatibilité logs restaurée guild=%s : %s route(s) legacy récupérée(s).",
            guild.id,
            repaired,
        )
    return repaired


async def sync_generated_logs(bot: commands.Bot, guild: discord.Guild) -> int:
    """Complète seulement les routes encore absentes après la migration legacy."""
    await repair_legacy_routes(bot, guild)

    found: dict[str, discord.TextChannel] = {}
    for log_type in LOG_CHANNEL_ALIASES:
        channel = _find_log_channel(guild, log_type)
        if channel is not None:
            found[log_type] = channel

    if not found:
        return 0

    try:
        await bot.db.ensure_guild(guild.id)
    except Exception:
        logger.debug("ensure_guild indisponible pour %s", guild.id, exc_info=True)

    synced = 0
    preserved = 0
    for log_type, channel in found.items():
        if log_type not in log_service.LOG_TYPES:
            continue

        try:
            row = await log_service._ensure_category_row(bot, guild.id, log_type)
            if row.get("channel_id"):
                # Une route existante (ancienne ou nouvelle) gagne toujours sur le nom
                # automatique du salon.
                preserved += 1
                continue

            if not bool(row.get("enabled", 1)):
                preserved += 1
                continue

            if await _explicitly_disabled(bot, guild.id, log_type):
                preserved += 1
                continue

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

    logger.info(
        "Synchronisation logs guild=%s : %s route(s) complétée(s), %s préservée(s).",
        guild.id,
        synced,
        preserved,
    )
    return synced


async def _bootstrap(bot: commands.Bot) -> None:
    try:
        await bot.wait_until_ready()
    except RuntimeError:
        return

    # Réaffirme les patches après le chargement des couches V73/V74/V83.
    _install_legacy_route_repair()
    _install_legacy_router_aliases()
    _install_atomic_log_route_save()
    _install_setup_log_callbacks()

    await asyncio.sleep(2)
    total_repaired = 0
    for guild in list(bot.guilds):
        try:
            total_repaired += await repair_legacy_routes(bot, guild)
            await sync_generated_logs(bot, guild)
        except Exception:
            logger.exception(
                "Réparation/synchronisation des logs impossible sur %s (%s).",
                guild.name,
                guild.id,
            )

    logger.warning(
        "Bootstrap compatibilité logs terminé : %s ancienne(s) route(s) restaurée(s).",
        total_repaired,
    )


def install(bot: commands.Bot) -> None:
    from . import server_builder

    _install_legacy_route_repair()
    _install_legacy_router_aliases()
    _install_atomic_log_route_save()
    _install_setup_log_callbacks()

    original = server_builder.ServerBuilder._configure_bot_channels
    if not getattr(original, "_sentrix_log_settings_sync_v84", False):

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

        configure_with_log_sync._sentrix_log_settings_sync_v84 = True
        server_builder.ServerBuilder._configure_bot_channels = configure_with_log_sync

    if getattr(bot, "_sentrix_generated_logs_sync_installed_v84", False):
        return

    bot._sentrix_generated_logs_sync_installed_v84 = True
    asyncio.create_task(_bootstrap(bot), name="sentrix-generated-logs-sync-v84")
    logger.info(
        "Compatibilité LOGS V84 activée : anciennes configurations + log_config canonique."
    )
