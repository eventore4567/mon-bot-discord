"""SentriX V83 — autorité finale des logs larges et commandes slash /logs.

V81/V82 restent chargées pour leurs autres interfaces, mais ne doivent plus remplacer le
transport canonique de ``utils.log_service``. V83 restaure donc le ``send_log`` canonique,
qui route maintenant vers ``utils.wide_logs.send_wide_log`` après la configuration et la
déduplication existantes.
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

# Capturé au moment de l'import, avant premium_ui_v81/v82.install().
_CANONICAL_SEND_LOG = log_service.send_log

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


async def _traced_canonical_send_log(*args, **kwargs):
    """Point unique visible dans Railway avant le renderer V2 officiel."""
    guild = args[1] if len(args) > 1 else kwargs.get("guild")
    log_type = args[2] if len(args) > 2 else kwargs.get("log_type")
    event_key = kwargs.get("event_key")
    logger.warning(
        "SENTRIX ROUTE log_type=%s renderer=wide_logs guild=%s event_key=%s",
        log_type,
        getattr(guild, "id", None),
        event_key,
    )
    return await _CANONICAL_SEND_LOG(*args, **kwargs)


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
    """Force le Cog Logs officiel à passer par le transport canonique V2."""
    from . import logs as logs_cog

    log_type = logs_cog.CONFIG_TO_LOG_TYPE.get(config_key)
    if log_type is None:
        return False
    return await log_service.send_log(
        self.bot,
        guild,
        log_type,
        embed,
        view=view,
        event_key=event_key,
    )


def _restore_unique_log_transport() -> None:
    """Retire les anciens transports globaux et restaure un seul pipeline de logs."""
    log_service.send_log = _traced_canonical_send_log

    # embeds.py avait un ancien filet global Messageable.send destiné aux vieux logs
    # directs. Il laissait justement passer des embeds classiques. V83 le retire : le
    # Cog Logs officiel doit désormais passer uniquement par log_service -> wide_logs.
    current_send = discord.abc.Messageable.send
    if getattr(current_send, "_sentrix_log_transport_guard", False):
        original_send = getattr(current_send, "_sentrix_original_send", None)
        if original_send is not None:
            discord.abc.Messageable.send = original_send
            logger.info("V83: ancien guard global Messageable.send retiré.")

    try:
        from . import logs as logs_cog

        logs_cog.Logs._send = _canonical_logs_send_v83
        logger.info(
            "V83: Cog Logs verrouillé sur log_service.send_log -> send_wide_log "
            "(Message supprimé inclus)."
        )
    except Exception:
        logger.exception("V83: impossible de verrouiller le Cog Logs sur le transport canonique.")


def _legacy_member_template(embed: discord.Embed | None, content: object) -> bool:
    """Reconnaît uniquement les vieux panneaux membre réellement cassés.

    Ils sont la source du second message Bienvenue/Départ visible avec ``{mention}`` ou
    ``{user}``. On ne bloque jamais un panneau configuré valide.
    """
    if not isinstance(embed, discord.Embed):
        return False
    parts = [str(content or ""), str(embed.title or ""), str(embed.description or "")]
    for field in embed.fields:
        parts.extend((str(field.name or ""), str(field.value or "")))
    blob = "\n".join(parts)
    if "{mention}" not in blob and "{user}" not in blob:
        return False
    title = str(embed.title or "").casefold()
    return title.startswith("bienvenue sur") or "départ d’un membre" in title or "depart d'un membre" in title


def _install_legacy_member_panel_guard() -> None:
    """Supprime le second panneau legacy sans toucher au vrai système bienvenue/départ."""
    current_send = discord.TextChannel.send
    if getattr(current_send, "_sentrix_v83_member_panel_guard", False):
        return

    async def guarded_send(channel: discord.TextChannel, *args, **kwargs):
        embed = kwargs.get("embed")
        content = kwargs.get("content")
        if content is None and args:
            content = args[0]
        if _legacy_member_template(embed, content):
            logger.warning(
                "SENTRIX DUPLICATE blocked=legacy_member_panel guild=%s channel=%s title=%r",
                getattr(getattr(channel, "guild", None), "id", None),
                getattr(channel, "id", None),
                getattr(embed, "title", None),
            )
            return None
        return await current_send(channel, *args, **kwargs)

    guarded_send._sentrix_v83_member_panel_guard = True
    guarded_send._sentrix_original_send = current_send
    discord.TextChannel.send = guarded_send
    logger.info("V83: panneaux Bienvenue/Départ legacy avec placeholders bloqués.")


def _install_ticket_reassignment_race_fix() -> None:
    """Empêche une ancienne copie du cache de déclaim un ticket déjà repris.

    Mastery gardait un snapshot jusqu'à 45 s. Un claim récent pouvait donc être écrasé par
    la passe de réattribution. La décision est maintenant recalculée sur la ligne DB fraîche,
    puis le déclaim utilise un UPDATE conditionnel sur le même claimant + last_activity_at.
    """
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
                abandoned = member is None or (
                    last_activity
                    and ts - last_activity >= mastery.TICKET_REASSIGN_SECONDS
                    and (
                        not last_seen
                        or time.monotonic() - last_seen >= mastery.TICKET_REASSIGN_SECONDS
                    )
                )
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
                    # Un claim ou une activité vient d'arriver entre la lecture et l'UPDATE.
                    # On laisse strictement le nouvel état intact.
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

    ok, reason = log_service.validate_channel(guild, setting["channel_id"])
    if not ok:
        return False, f"Impossible d'envoyer un test : {reason}."

    test_embed = embeds.log_embed(
        "Test de log",
        fields=(
            ("Catégorie", log_service.LOG_TYPES.get(log_type, {}).get("label", log_type), False),
            ("Déclenché par", f"<@{author.id}>", True),
        ),
    )
    channel = guild.get_channel(setting["channel_id"])
    sent = await send_wide_log(
        channel,
        test_embed,
        log_type=log_type,
    )
    return (
        (True, f"Test envoyé dans {channel.mention}.")
        if sent
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
            logger.warning("Fallback historique classique après échec Components V2.", exc_info=True)
            await interaction.followup.send(
                embed=history_embed,
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

    # Force une régénération unique au démarrage afin que les anciens PNG avec trou
    # transparent soient remplacés, même s'ils existent déjà sur le disque Railway.
    ensure_banners(force=True)

    # V81/V82 viennent d'être installées juste avant. On restaure volontairement la
    # fonction canonique modifiée dans utils/log_service.py pour que config et dédup restent
    # exactement celles du service officiel avant de déléguer à send_wide_log().
    _restore_unique_log_transport()
    log_service.send_test_log = _send_test_log_v83

    # Correctifs finaux des chemins legacy encore observés en production.
    _install_legacy_member_panel_guard()
    _install_ticket_reassignment_race_fix()

    _install_slash_group(bot)
    try:
        asyncio.create_task(ensure_log_storage())
    except RuntimeError:
        logger.debug("V83: initialisation SQLite différée jusqu'au premier log.")

    bot._sentrix_logs_runtime_v83 = True
    logger.info(
        "%s installé : logger canonique restauré, Components V2 larges et commandes /logs actives.",
        RUNTIME_MARKER,
    )


__all__ = ["LogsSlashGroup", "install"]