"""Compatibilité +setup/Create Logs et réparations de routage des logs par catégorie.

Ce module garde les salons historiques reliés au moteur moderne de logs sans écraser un
salon personnalisé choisi par un administrateur. Il répare aussi les anciennes routes
croisées (par exemple Salons pointant par erreur vers Modération) et force les fermetures
de tickets à passer par le renderer officiel Components V2.
"""
from __future__ import annotations

import asyncio
import html
import io
import logging

import discord
from discord.ext import commands

from utils import log_service

logger = logging.getLogger("bot.setup-create-logs-sync")

# Colonnes historiques -> catégories modernes.
# ``log_server`` signifiait historiquement les événements de SALONS.
COLUMN_TO_LOG_TYPE = {
    "log_server": "channels",
    "log_messages": "messages",
    "log_members": "members",
    "log_voice": "voice",
    "log_roles": "roles",
    "log_moderation": "moderation",
    "log_automod": "protection",
    "ticket_log_channel": "tickets",
}


def _configured_channel(guild: discord.Guild, conf, column: str) -> discord.TextChannel | None:
    if not conf:
        return None
    try:
        channel_id = conf[column]
    except (KeyError, IndexError, TypeError):
        return None
    if not channel_id:
        return None
    try:
        channel = guild.get_channel(int(channel_id))
    except (TypeError, ValueError):
        return None
    return channel if isinstance(channel, discord.TextChannel) else None


async def sync_setup_created_logs(
    bot: commands.Bot,
    guild: discord.Guild,
    *,
    force_enable: bool,
) -> int:
    """Synchronise les salons historiques avec les catégories modernes.

    Une route personnalisée reste intacte. En revanche, si une catégorie pointe vers le
    salon généré pour UNE AUTRE catégorie, c'est forcément une migration croisée : elle est
    replacée sur son salon attendu.
    """
    conf = await bot.db.get_guild_config(guild.id)
    if not conf:
        return 0

    expected: dict[str, discord.TextChannel] = {}
    for column, category in COLUMN_TO_LOG_TYPE.items():
        channel = _configured_channel(guild, conf, column)
        if channel is not None:
            expected[category] = channel

    expected_ids = {channel.id for channel in expected.values()}
    synced = 0
    moderation_channel_id = expected.get("moderation").id if expected.get("moderation") else None

    for category, channel in expected.items():
        try:
            setting = await log_service.get_log_setting(bot, guild.id, category)
        except Exception:
            logger.exception("Lecture de la route %s impossible sur %s.", category, guild.id)
            continue

        current_id = setting.get("dedicated_channel_id")
        current_channel = guild.get_channel(int(current_id)) if current_id else None
        crossed_route = bool(
            current_id
            and int(current_id) != channel.id
            and int(current_id) in expected_ids
        )
        missing_or_invalid = not current_id or not isinstance(current_channel, discord.TextChannel)

        if force_enable or missing_or_invalid or crossed_route:
            if crossed_route:
                logger.warning(
                    "Route de logs croisée réparée guild=%s catégorie=%s ancien=%s attendu=%s",
                    guild.id,
                    category,
                    current_id,
                    channel.id,
                )
            await log_service.set_log_channel(bot, guild.id, category, channel.id)

            # Un clic explicite sur Create Logs active les routes. Pour un bootstrap, on
            # réactive uniquement une route absente/croisée issue des salons générés ; une
            # désactivation volontaire avec un salon personnalisé valide reste intacte.
            if force_enable or missing_or_invalid or crossed_route:
                await log_service.set_log_enabled(bot, guild.id, category, True)
            synced += 1

    # Le salon de modération reste le repli général historique uniquement si aucun repli
    # valide n'existe. Les catégories dédiées restent prioritaires.
    if moderation_channel_id:
        try:
            current_general = conf["log_channel"]
        except (KeyError, IndexError, TypeError):
            current_general = None
        if not current_general or guild.get_channel(int(current_general)) is None:
            await bot.db.set_guild_config(guild.id, "log_channel", moderation_channel_id)

    if synced:
        logger.info(
            "Create Logs synchronisé sur %s (%s) : %s route(s) réparée(s).",
            guild.name,
            guild.id,
            synced,
        )
    return synced


def _ticket_html_file(filename: str, transcript_text: str) -> discord.File:
    """Crée un transcript HTML autonome et lisible hors de Discord."""
    safe = html.escape(transcript_text or "Aucun message.")
    document = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Transcript SentriX</title>
<style>
body{{margin:0;background:#0f1020;color:#ececf4;font:15px/1.55 system-ui,-apple-system,sans-serif}}
main{{max-width:980px;margin:32px auto;padding:28px;background:#181a2d;border:1px solid #30334f;border-radius:16px}}
h1{{margin:0 0 20px;font-size:24px}}pre{{white-space:pre-wrap;word-break:break-word;font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}}
small{{color:#9ea3bd}}
</style>
</head><body><main><h1>Transcript du ticket</h1><pre>{safe}</pre><small>Généré par SentriX</small></main></body></html>"""
    return discord.File(io.BytesIO(document.encode("utf-8")), filename=filename)


def _ticket_transcript_view(ticket_id: int, filename: str, transcript_text: str) -> discord.ui.View:
    """Bouton Transcript du log ; le fichier joint au panneau reste aussi téléchargeable."""
    view = discord.ui.View(timeout=None)
    button = discord.ui.Button(
        label="Transcript",
        emoji="📁",
        style=discord.ButtonStyle.secondary,
        custom_id=f"sentrix_ticket_transcript:{int(ticket_id)}",
    )

    async def callback(interaction: discord.Interaction):
        try:
            await interaction.response.send_message(
                file=_ticket_html_file(filename, transcript_text),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Le transcript n'a pas pu être renvoyé. Utilisez le fichier HTML joint au log.",
                    ephemeral=True,
                )

    button.callback = callback
    view.add_item(button)
    return view


def _install_ticket_log_patch(bot: commands.Bot) -> bool:
    """Fait passer ouverture/fermeture de tickets par log_service + WideLogView."""
    try:
        from . import tickets as tickets_mod
    except Exception:
        logger.exception("Impossible d'importer le module tickets pour le routage des logs.")
        return False

    tickets_cls = getattr(tickets_mod, "Tickets", None)
    if tickets_cls is None:
        return False

    # Les ouvertures et fermetures automatiques utilisaient encore un envoi embed direct
    # lorsqu'un salon par type était configuré. Le renderer officiel devient l'unique sortie.
    current_log_action = tickets_cls.log_action
    if not getattr(current_log_action, "_sentrix_category_log_action", False):
        async def log_action_category(self, guild, embed, log_channel_id=None):
            return await log_service.send_log(self.bot, guild, "tickets", embed)

        log_action_category._sentrix_category_log_action = True
        log_action_category._sentrix_original = current_log_action
        tickets_cls.log_action = log_action_category

    current_close = tickets_cls.close_ticket
    if getattr(current_close, "_sentrix_ticket_close_v2", False):
        return True

    async def close_ticket_v2(self, interaction: discord.Interaction, ticket_id: int, reason: str):
        ticket = await self.bot.db.fetchone("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if not ticket or interaction.guild is None:
            return
        channel = interaction.guild.get_channel(ticket["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return

        conf = await self.bot.db.get_guild_config(interaction.guild.id)
        closed_at = int(__import__("time").time())
        await self.bot.db.execute(
            "UPDATE tickets SET status='ferme', closed_at=?, locked=1 WHERE id=?",
            (closed_at, ticket_id),
        )

        owner = interaction.guild.get_member(int(ticket["user_id"]))
        if owner:
            overwrite = channel.overwrites_for(owner)
            overwrite.send_messages = False
            try:
                await channel.set_permissions(owner, overwrite=overwrite)
            except discord.HTTPException:
                pass

        try:
            transcript_text = await self._fetch_transcript_text(channel)
        except discord.HTTPException:
            transcript_text = "Transcription indisponible (erreur lors de la lecture du salon)."

        filename = f"{int(ticket['user_id'])}-ticket-{int(ticket_id)}.html"
        created_at = int(ticket["created_at"] or closed_at)
        reason_text = (reason or "Non précisée").strip()[:1200]

        participants = []
        for member in channel.members:
            if member.bot:
                continue
            participants.append(f"{member.display_name} (`{member.id}`)")
        if not participants and owner:
            participants.append(f"{owner.display_name} (`{owner.id}`)")
        participants_text = "\n".join(participants[:30]) or "Aucun participant disponible."

        member_ref = f"<@{int(ticket['user_id'])}> (`{int(ticket['user_id'])}`)"
        moderator_ref = f"<@{interaction.user.id}> (`{interaction.user.id}`)"
        description = (
            f"**Modérateur :** {moderator_ref}\n"
            f"**Membre :** {member_ref}\n"
            f"**Création du ticket :** <t:{created_at}:R>\n"
            f"**Transcript :** fichier HTML joint au log\n\n"
            f"**Raison :** {reason_text}\n\n"
            f"**Participants :**\n{participants_text}"
        )
        log_embed = discord.Embed(
            title="Fermeture du ticket",
            description=description[:3900],
            colour=discord.Colour(0xA05CFF),
            timestamp=discord.utils.utcnow(),
        )
        log_embed.set_footer(text="SentriX")

        identity_name = (
            owner.display_name if owner else f"Membre {int(ticket['user_id'])}"
        )
        identity_icon = str(owner.display_avatar.url) if owner else None
        event_key = log_service.make_event_key(
            interaction.guild.id,
            "ticket_close",
            target_id=int(ticket["user_id"]),
            executor_id=interaction.user.id,
            discriminator=ticket_id,
        )
        transcript_view = _ticket_transcript_view(ticket_id, filename, transcript_text)

        sent = await log_service.send_log(
            self.bot,
            interaction.guild,
            "ticket_close",
            log_embed,
            file=_ticket_html_file(filename, transcript_text),
            view=transcript_view,
            event_key=event_key,
            identity_name=identity_name,
            identity_id=int(ticket["user_id"]),
            identity_icon=identity_icon,
        )
        if not sent:
            logger.warning("Log de fermeture ticket #%s non envoyé par le renderer V2.", ticket_id)

        delay = (conf["ticket_delete_delay"] if conf else 30) or 30
        asyncio.create_task(self._auto_delete(channel, ticket_id, delay))

        try:
            await channel.send(
                embed=__import__("utils.embeds", fromlist=["warning"]).warning(
                    f"🔒 Ticket fermé par {interaction.user.mention}.\nRaison : {reason_text}\n\n"
                    f"Suppression automatique dans **{__import__('utils.helpers', fromlist=['format_duration']).format_duration(delay)}**."
                ),
                file=_ticket_html_file(filename, transcript_text),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            pass

        if owner and (not conf or conf["ticket_transcript_dm"]):
            try:
                from utils import embeds as embeds_mod
                await owner.send(
                    embed=embeds_mod.info(
                        f"Voici la transcription de votre ticket sur **{interaction.guild.name}**."
                    ),
                    file=_ticket_html_file(filename, transcript_text),
                )
            except (discord.Forbidden, discord.HTTPException):
                pass
            if not conf or conf["ticket_rating_enabled"]:
                try:
                    await owner.send(
                        content="Pouvez-vous noter le support reçu ?",
                        view=tickets_mod.RatingView(self, ticket_id),
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

    close_ticket_v2._sentrix_ticket_close_v2 = True
    close_ticket_v2._sentrix_original = current_close
    tickets_cls.close_ticket = close_ticket_v2
    logger.info("Fermeture ticket -> logs-tickets Components V2 activée.")
    return True


async def _bootstrap(bot: commands.Bot) -> None:
    try:
        await bot.wait_until_ready()
    except RuntimeError:
        return
    await asyncio.sleep(3)
    for guild in list(bot.guilds):
        try:
            await sync_setup_created_logs(bot, guild, force_enable=False)
        except Exception:
            logger.exception("Réparation Create Logs impossible sur %s (%s).", guild.name, guild.id)


def install(bot: commands.Bot) -> None:
    """Installe la synchro de catégories et le correctif ticket une seule fois."""
    from . import configuration

    original = configuration.Configuration.create_log_channels
    if not getattr(original, "_sentrix_log_settings_sync", False):
        async def create_log_channels_synced(self, guild, author):
            created = await original(self, guild, author)
            await sync_setup_created_logs(self.bot, guild, force_enable=True)
            return created

        create_log_channels_synced._sentrix_log_settings_sync = True
        configuration.Configuration.create_log_channels = create_log_channels_synced

    _install_ticket_log_patch(bot)

    if getattr(bot, "_sentrix_setup_create_logs_sync_installed", False):
        return
    bot._sentrix_setup_create_logs_sync_installed = True
    asyncio.create_task(_bootstrap(bot), name="sentrix-setup-create-logs-sync")
    logger.info("Synchronisation Create Logs + logs tickets V2 activée.")
