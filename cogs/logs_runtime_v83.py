"""SentriX V83 — autorité finale des logs larges et commandes slash /logs.

V83 impose un transport unique : ``cogs.logs`` -> ``utils.log_service`` ->
``utils.wide_logs``. Les anciens overrides d'instance et monkey-patches de send sont
activement retirés au démarrage avant le premier vrai événement.
"""
from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, log_service
from utils.log_banners import banner_kind, ensure_banners, get_banner
from utils.wide_logs import (
    NO_PINGS,
    WideLogView,
    ensure_log_storage,
    fetch_log_history,
    send_wide_log,
    upsert_log_config,
)

logger = logging.getLogger("bot.logs-runtime-v83")
RUNTIME_MARKER = "Wide Logs Runtime V83"

_LOG_CHOICES = [
    app_commands.Choice(name="Messages", value="messages"),
    app_commands.Choice(name="Membres", value="members"),
    app_commands.Choice(name="Rôles", value="roles"),
    app_commands.Choice(name="Salons / serveur", value="server"),
    app_commands.Choice(name="Vocal", value="voice"),
    app_commands.Choice(name="Modération", value="moderation"),
    app_commands.Choice(name="Tickets", value="tickets"),
    app_commands.Choice(name="Sécurité / AutoMod", value="automod"),
]


def _can_manage_logs(interaction: discord.Interaction) -> bool:
    member = interaction.user
    return bool(
        isinstance(member, discord.Member)
        and (member.guild_permissions.administrator or member.guild_permissions.manage_guild)
    )


async def _deny(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        "Vous devez avoir la permission **Gérer le serveur** pour utiliser cette commande.",
        ephemeral=True,
        allowed_mentions=NO_PINGS,
    )


async def _traced_canonical_send_log(
    bot,
    guild: discord.Guild,
    log_type: str,
    embed: discord.Embed,
    file: discord.File | None = None,
    *,
    view: discord.ui.View | None = None,
    event_key: str | None = None,
) -> bool:
    """Transport V83 autonome.

    Important : cette fonction ne délègue jamais à ``log_service.send_log``. Une ancienne
    couche V33 pouvait remplacer ce symbole avant l'import de V83 ; capturer ce wrapper
    rendait ensuite ``event_key`` incompatible. V83 utilise directement les primitives
    stables de ``log_service`` et le renderer ``send_wide_log``.
    """
    logger.warning(
        "SENTRIX ROUTE log_type=%s renderer=wide_logs guild=%s event_key=%s",
        log_type,
        getattr(guild, "id", None),
        event_key,
    )

    if log_type not in log_service.LOG_TYPES:
        logger.error("SENTRIX ROUTE type inconnu=%s", log_type)
        return False

    if not log_service.is_primary_process():
        logger.info(
            "Log volontairement désactivé par SENTRIX_LOG_PRODUCER guild=%s type=%s",
            guild.id,
            log_type,
        )
        return False

    rendered = (
        embed
        if getattr(getattr(embed, "image", None), "url", None) == embeds.SENTRIX_BANNER_URL
        else embeds.normalize_log(embed)
    )

    semantic_key = log_service.semantic_event_key(guild.id, log_type, rendered)
    if log_service._is_duplicate(event_key) or log_service._is_duplicate(semantic_key):
        logger.debug(
            "Log dupliqué ignoré guild=%s type=%s key=%s",
            guild.id,
            log_type,
            event_key or semantic_key,
        )
        return False

    try:
        setting = await log_service.get_log_setting(bot, guild.id, log_type)
    except Exception:
        logger.exception(
            "SENTRIX ROUTE configuration illisible guild=%s type=%s",
            guild.id,
            log_type,
        )
        return False

    if not setting.get("enabled"):
        logger.info("Log désactivé guild=%s type=%s", guild.id, log_type)
        return False

    ok, reason = log_service.validate_channel(
        guild,
        setting.get("channel_id"),
        needs_file=True,
    )
    if not ok:
        logger.warning(
            "SENTRIX ROUTE invalide guild=%s type=%s reason=%s",
            guild.id,
            log_type,
            reason,
        )
        return False

    channel = guild.get_channel(int(setting.get("channel_id") or 0))
    if not isinstance(channel, discord.TextChannel):
        logger.warning(
            "SENTRIX ROUTE salon absent guild=%s type=%s channel=%s",
            guild.id,
            log_type,
            setting.get("channel_id"),
        )
        return False

    try:
        return bool(await send_wide_log(
            channel,
            rendered,
            log_type=log_type,
            old_view=view,
            extra_file=file,
        ))
    except Exception:
        logger.exception(
            "SENTRIX ROUTE V2 échouée guild=%s type=%s",
            guild.id,
            log_type,
        )
        return False


_traced_canonical_send_log._sentrix_v83_trace = True


async def _canonical_logs_send_v83(
    self,
    guild: discord.Guild,
    config_key: str,
    embed: discord.Embed,
    *,
    view: discord.ui.View | None = None,
    event_key: str | None = None,
) -> bool:
    from . import logs as logs_cog

    log_type = logs_cog.CONFIG_TO_LOG_TYPE.get(config_key)
    if log_type is None:
        return False
    # Appel DIRECT : même si une vieille couche réécrit log_service.send_log plus tard,
    # les 18 listeners officiels restent verrouillés sur V83.
    return await _traced_canonical_send_log(
        self.bot,
        guild,
        log_type,
        embed,
        view=view,
        event_key=event_key,
    )


def _unwrap_send(function):
    current = function
    seen: set[int] = set()
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        original = (
            getattr(current, "_sentrix_original_send", None)
            or getattr(current, "_sentrix_original", None)
        )
        if not callable(original):
            break
        current = original
    return current


def _restore_native_sends() -> None:
    logger.warning(
        "SEND PATCHED BEFORE RESTORE = %s | qualname=%s | module=%s",
        discord.TextChannel.send is not discord.abc.Messageable.send,
        getattr(discord.TextChannel.send, "__qualname__", "?"),
        getattr(discord.TextChannel.send, "__module__", "?"),
    )

    native_messageable_send = _unwrap_send(discord.abc.Messageable.send)
    native_text_send = _unwrap_send(discord.TextChannel.send)

    if callable(native_messageable_send):
        discord.abc.Messageable.send = native_messageable_send

    if callable(native_messageable_send):
        discord.TextChannel.send = native_messageable_send
    elif callable(native_text_send):
        discord.TextChannel.send = native_text_send

    logger.warning(
        "SEND PATCHED = %s | qualname=%s | module=%s",
        discord.TextChannel.send is not discord.abc.Messageable.send,
        getattr(discord.TextChannel.send, "__qualname__", "?"),
        getattr(discord.TextChannel.send, "__module__", "?"),
    )


def _restore_unique_log_transport(bot: commands.Bot) -> None:
    _restore_native_sends()

    stale_global = log_service.send_log
    logger.warning(
        "SENTRIX ROUTE previous log_service.send_log=%s.%s",
        getattr(stale_global, "__module__", "?"),
        getattr(stale_global, "__qualname__", "?"),
    )
    log_service.send_log = _traced_canonical_send_log
    logger.warning(
        "SENTRIX ROUTE log_service.send_log canonical=%s | qualname=%s.%s",
        log_service.send_log is _traced_canonical_send_log,
        getattr(log_service.send_log, "__module__", "?"),
        getattr(log_service.send_log, "__qualname__", "?"),
    )

    try:
        from . import logs as logs_cog

        active_cog = bot.get_cog("Logs")
        if active_cog is not None and "_send" in vars(active_cog):
            stale = vars(active_cog).get("_send")
            stale_func = getattr(stale, "__func__", stale)
            logger.warning(
                "SENTRIX ROUTE stale Logs._send instance override removed | qualname=%s | module=%s",
                getattr(stale_func, "__qualname__", "?"),
                getattr(stale_func, "__module__", "?"),
            )
            delattr(active_cog, "_send")

        logs_cog.Logs._send = _canonical_logs_send_v83

        active_cog = bot.get_cog("Logs")
        resolved = getattr(active_cog, "_send", None) if active_cog is not None else None
        resolved_func = getattr(resolved, "__func__", resolved)
        logger.warning(
            "SENTRIX ROUTE Logs._send canonical=%s | instance_override=%s | qualname=%s | module=%s",
            bool(resolved_func is _canonical_logs_send_v83),
            bool(active_cog is not None and "_send" in vars(active_cog)),
            getattr(resolved_func, "__qualname__", "?"),
            getattr(resolved_func, "__module__", "?"),
        )
    except Exception:
        logger.exception("V83: impossible de verrouiller le Cog Logs sur le transport canonique.")


def _install_ticket_reassignment_race_fix() -> None:
    try:
        from . import bot_mastery_runtime as mastery
    except Exception:
        logger.exception("V83: runtime Mastery indisponible pour le correctif ticket.")
        return

    cls = mastery.BotMasteryRuntime
    current = cls._ticket_reassignment_pass
    if getattr(current, "_sentrix_v83_fresh_claim_guard", False):
        return

    async def safe_ticket_reassignment(self):
        ts = int(time.time())
        for channel_id, cached in list(self._ticket_channels.items()):
            try:
                fresh_row = await self.bot.db.fetchone(
                    "SELECT id,guild_id,channel_id,user_id,priority,claimed_by,last_activity_at,status "
                    "FROM tickets WHERE id=?",
                    (cached["id"],),
                )
                if not fresh_row or fresh_row["status"] != "ouvert":
                    continue
                ticket = dict(fresh_row)
                self._ticket_channels[int(channel_id)] = ticket
                claimed_by = ticket.get("claimed_by")
                if not claimed_by:
                    continue

                guild = self.bot.get_guild(int(ticket["guild_id"]))
                if guild is None:
                    continue
                member = guild.get_member(int(claimed_by))
                last_seen = self._member_activity.get((guild.id, int(claimed_by)), 0.0)
                last_activity = int(ticket.get("last_activity_at") or 0)

                stale_claim = bool(
                    last_activity
                    and ts - last_activity >= mastery.TICKET_REASSIGN_SECONDS
                )
                staff_inactive = bool(
                    member is None
                    or not last_seen
                    or time.monotonic() - last_seen >= mastery.TICKET_REASSIGN_SECONDS
                )
                abandoned = stale_claim and staff_inactive
                if not abandoned:
                    continue

                state_row = await self.bot.db.fetchone(
                    "SELECT reassigned_count FROM ticket_mastery_state WHERE ticket_id=?",
                    (ticket["id"],),
                )
                if state_row and int(state_row["reassigned_count"] or 0) >= 2:
                    continue

                reservation = await self.bot.db.execute(
                    "UPDATE tickets SET claimed_by=NULL "
                    "WHERE id=? AND status='ouvert' AND claimed_by=? "
                    "AND COALESCE(last_activity_at,0)=?",
                    (ticket["id"], int(claimed_by), last_activity),
                )
                if reservation.rowcount < 1:
                    newest = await self.bot.db.fetchone(
                        "SELECT id,guild_id,channel_id,user_id,priority,claimed_by,last_activity_at,status "
                        "FROM tickets WHERE id=?",
                        (ticket["id"],),
                    )
                    if newest:
                        self._ticket_channels[int(channel_id)] = dict(newest)
                    logger.info(
                        "Ticket %s : réattribution annulée car le claim a changé entre-temps.",
                        ticket["id"],
                    )
                    continue

                await self.bot.db.execute(
                    "INSERT INTO ticket_mastery_state "
                    "(ticket_id,priority,last_claimed_by,claim_last_seen,reassigned_count,updated_at) "
                    "VALUES (?,?,?,?,1,?) ON CONFLICT(ticket_id) DO UPDATE SET "
                    "last_claimed_by=excluded.last_claimed_by, "
                    "reassigned_count=reassigned_count+1, updated_at=excluded.updated_at",
                    (
                        ticket["id"],
                        ticket.get("priority") or "normale",
                        int(claimed_by),
                        int(last_seen or 0),
                        ts,
                    ),
                )
                channel = guild.get_channel(int(channel_id))
                if isinstance(channel, discord.TextChannel):
                    try:
                        await channel.send(
                            "Ce ticket a été remis dans la file staff car sa prise en charge était inactive."
                        )
                    except discord.HTTPException:
                        pass
                ticket["claimed_by"] = None
                self._ticket_channels[int(channel_id)] = ticket
            except Exception:
                logger.exception(
                    "V83: échec isolé du contrôle de réattribution ticket id=%s",
                    cached.get("id") if isinstance(cached, dict) else None,
                )

    safe_ticket_reassignment._sentrix_v83_fresh_claim_guard = True
    safe_ticket_reassignment._sentrix_original = current
    cls._ticket_reassignment_pass = safe_ticket_reassignment
    logger.info("V83: course claim/réattribution tickets corrigée par relecture DB atomique.")


async def _send_test_log_v83(
    bot,
    guild: discord.Guild,
    log_type: str,
    author: discord.abc.User,
) -> tuple[bool, str]:
    setting = await log_service.get_log_setting(bot, guild.id, log_type)
    if not setting["enabled"]:
        return False, "Ce type de log est désactivé. Activez-le avant le test."

    ok, reason = log_service.validate_channel(guild, setting["channel_id"], needs_file=True)
    if not ok:
        return False, f"Impossible d'envoyer un test : {reason}."

    test_embed = embeds.log_embed(
        "Test de log",
        fields=(
            ("Catégorie", log_service.LOG_TYPES.get(log_type, {}).get("label", log_type), False),
            ("Déclenché par", f"<@{author.id}>", True),
        ),
    )
    sent = await _traced_canonical_send_log(
        bot,
        guild,
        log_type,
        test_embed,
        event_key=f"manual-test:{guild.id}:{log_type}:{time.time_ns()}",
    )
    channel = guild.get_channel(setting["channel_id"])
    return (
        (True, f"Test envoyé dans {channel.mention}.")
        if sent and channel is not None
        else (False, "Le test n'a pas pu être envoyé dans le salon de logs.")
    )


class LogsSlashGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(name="logs", description="Configurer et consulter les logs SentriX.")
        self.bot = bot

    @app_commands.command(name="config", description="Choisir le salon et l'état d'un type de logs.")
    @app_commands.describe(
        log_type="Type de logs à configurer",
        salon="Salon qui recevra ce type de logs",
        actif="Activer ou désactiver ce type de logs",
    )
    @app_commands.choices(log_type=_LOG_CHOICES)
    async def config_command(
        self,
        interaction: discord.Interaction,
        log_type: app_commands.Choice[str],
        salon: discord.TextChannel | None = None,
        actif: bool | None = None,
    ) -> None:
        if interaction.guild is None:
            return await interaction.response.send_message(
                "Cette commande doit être utilisée dans un serveur.",
                ephemeral=True,
            )
        if not _can_manage_logs(interaction):
            return await _deny(interaction)

        await interaction.response.defer(ephemeral=True)
        guild_id = int(interaction.guild.id)
        key = str(log_type.value)

        try:
            setting = await log_service.get_log_setting(self.bot, guild_id, key)
            if salon is not None:
                setting = await log_service.set_log_channel(self.bot, guild_id, key, salon.id)

            if actif is not None:
                try:
                    setting = await log_service.set_log_enabled(self.bot, guild_id, key, actif)
                except ValueError as exc:
                    if str(exc) == "channel_required":
                        return await interaction.followup.send(
                            "Choisissez d'abord un **salon** avant d'activer ce type de logs.",
                            ephemeral=True,
                        )
                    raise

            setting = await log_service.get_log_setting(self.bot, guild_id, key)
            await upsert_log_config(
                guild_id,
                key,
                setting.get("channel_id"),
                bool(setting.get("enabled")),
            )
        except Exception:
            logger.exception("Échec de /logs config guild=%s type=%s", guild_id, key)
            return await interaction.followup.send(
                "Impossible de modifier la configuration des logs pour le moment.",
                ephemeral=True,
            )

        configured_channel = interaction.guild.get_channel(setting.get("channel_id")) if setting.get("channel_id") else None
        channel_text = configured_channel.mention if configured_channel is not None else "Aucun salon"
        state = "Activé" if setting.get("enabled") else "Désactivé"
        await interaction.followup.send(
            f"**{log_type.name}** · {state}\nSalon : {channel_text}",
            ephemeral=True,
            allowed_mentions=NO_PINGS,
        )

    @app_commands.command(name="history", description="Afficher les 10 derniers logs concernant un membre.")
    @app_commands.describe(membre="Membre dont vous voulez consulter l'historique")
    async def history_command(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
    ) -> None:
        if interaction.guild is None:
            return await interaction.response.send_message(
                "Cette commande doit être utilisée dans un serveur.",
                ephemeral=True,
            )
        if not _can_manage_logs(interaction):
            return await _deny(interaction)

        await interaction.response.defer(ephemeral=True)

        try:
            rows = await fetch_log_history(interaction.guild.id, membre.id, limit=10)
        except Exception:
            logger.exception("Échec de /logs history guild=%s target=%s", interaction.guild.id, membre.id)
            return await interaction.followup.send(
                "Impossible de lire l'historique des logs pour le moment.",
                ephemeral=True,
            )

        if not rows:
            return await interaction.followup.send(
                f"Aucun log enregistré pour {membre.mention} depuis l'activation de l'historique.",
                ephemeral=True,
                allowed_mentions=NO_PINGS,
            )

        history_embed = discord.Embed(
            title=f"Historique de {membre.display_name}",
            description="10 derniers événements enregistrés par SentriX.",
            colour=discord.Colour(0x6D5DFB),
        )
        history_embed.set_thumbnail(url=membre.display_avatar.url)

        for row in rows[:10]:
            created_at = int(row.get("created_at") or time.time())
            log_type = str(row.get("log_type") or "log")
            label = log_service.LOG_TYPES.get(log_type, {}).get("label", log_type)
            title = str(row.get("title") or "Événement")
            description = str(row.get("description") or "").replace("\n", " ").strip()
            if len(description) > 220:
                description = description[:219].rstrip() + "…"
            moderator_id = row.get("moderator_id")
            moderator = f" · Modérateur <@{moderator_id}>" if moderator_id else ""
            value = f"**{title}**{moderator}"
            if description:
                value += f"\n{description}"
            history_embed.add_field(
                name=f"<t:{created_at}:R> · {label}",
                value=value[:1000],
                inline=False,
            )

        kind = banner_kind("history", history_embed.title or "", history_embed.description or "")
        banner_path = get_banner("history", history_embed.title or "", history_embed.description or "")
        banner_filename = f"sentrix_log_{kind}.png"
        banner_file = discord.File(str(banner_path), filename=banner_filename)
        panel = WideLogView(
            history_embed,
            banner_filename,
            accent=history_embed.colour.value,
        )

        try:
            await interaction.followup.send(
                view=panel,
                file=banner_file,
                ephemeral=True,
                allowed_mentions=NO_PINGS,
            )
        except (discord.Forbidden, discord.HTTPException, OSError):
            logger.exception("Historique Components V2 impossible ; aucun fallback embed n'est autorisé.")
            await interaction.followup.send(
                "Impossible d'afficher cet historique en Components V2 pour le moment.",
                ephemeral=True,
                allowed_mentions=NO_PINGS,
            )


def _install_slash_group(bot: commands.Bot) -> None:
    existing = bot.tree.get_command("logs", type=discord.AppCommandType.chat_input)
    if existing is not None:
        if getattr(existing, "_sentrix_logs_v83", False):
            return
        logger.warning("V83: un groupe slash /logs existe déjà ; il n'est pas remplacé.")
        return

    group = LogsSlashGroup(bot)
    group._sentrix_logs_v83 = True
    bot.tree.add_command(group)
    bot._sentrix_logs_slash_v83 = group
    logger.info("V83: /logs config et /logs history enregistrés dans CommandTree.")


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_logs_runtime_v83", False):
        return

    ensure_banners(force=True)
    _restore_unique_log_transport(bot)
    log_service.send_test_log = _send_test_log_v83

    _install_ticket_reassignment_race_fix()
    _install_slash_group(bot)
    try:
        asyncio.create_task(ensure_log_storage())
    except RuntimeError:
        logger.debug("V83: initialisation SQLite différée jusqu'au premier log.")

    bot._sentrix_logs_runtime_v83 = True
    logger.info(
        "%s installé : logger canonique restauré, send natif, Components V2 larges et /logs actifs.",
        RUNTIME_MARKER,
    )


__all__ = [
    "LogsSlashGroup",
    "install",
    "_traced_canonical_send_log",
]
