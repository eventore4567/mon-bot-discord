"""Consultation privée des transcriptions depuis les logs de tickets.

Le salon de logs ne contient aucun jeton d'accès. Chaque clic vérifie le rôle
du membre et renvoie un lien personnel dans une réponse éphémère.
"""
from __future__ import annotations

import logging
import re

import discord

from cogs import language_runtime
from services import ticket_transcript_links

logger = logging.getLogger("bot.ticket-transcript-staff")


def staff_may_view(member: discord.Member, guild: discord.Guild, staff_role_id: int | None) -> bool:
    permissions = getattr(member, "guild_permissions", None)
    if member.id == guild.owner_id or getattr(permissions, "administrator", False):
        return True
    if getattr(permissions, "manage_channels", False):
        return True
    return bool(staff_role_id and any(
        int(role.id) == int(staff_role_id)
        for role in getattr(member, "roles", ())
    ))


class StaffTranscriptButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"sentrix:ticket:transcript:(?P<ticket_id>[0-9]{1,19})",
):
    def __init__(self, ticket_id: int):
        self.ticket_id = int(ticket_id)
        super().__init__(
            discord.ui.Button(
                label="Transcription privée",
                style=discord.ButtonStyle.secondary,
                custom_id=f"sentrix:ticket:transcript:{self.ticket_id}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(int(match.group("ticket_id")))

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        if guild is None or not isinstance(user, discord.Member):
            return await interaction.response.send_message(
                "Cette action est réservée au staff du serveur.", ephemeral=True
            )

        bot = interaction.client
        lang = await language_runtime.get_language(bot, guild.id)
        row = await bot.db.fetchone(
            "SELECT t.id, t.guild_id, t.channel_id, t.type_id, "
            "tt.staff_role_id "
            "FROM tickets t LEFT JOIN ticket_types tt ON tt.id = t.type_id "
            "WHERE t.id=? AND t.guild_id=?",
            (self.ticket_id, guild.id),
        )
        if row is None or not staff_may_view(user, guild, row["staff_role_id"]):
            text = language_runtime.text_for_language(
                lang, "Accès réservé au staff autorisé.",
                "Only authorized staff can access this transcript."
            )
            return await interaction.response.send_message(text, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        archived = await bot.db.fetchone(
            "SELECT channel_name, transcript_text FROM ticket_transcripts "
            "WHERE ticket_id=? AND guild_id=?",
            (self.ticket_id, guild.id),
        )
        if not archived:
            text = language_runtime.text_for_language(
                lang,
                "Aucune transcription archivée pour ce ticket.",
                "No saved transcript is available for this ticket."
            )
            return await interaction.followup.send(text, ephemeral=True)

        event = await bot.db.fetchone(
            "SELECT actor_id, details FROM ticket_events "
            "WHERE ticket_id=? AND guild_id=? AND event IN ('ticket_close','ticket_autoclose') "
            "ORDER BY id DESC LIMIT 1",
            (self.ticket_id, guild.id),
        )
        closer = f"<@{int(event['actor_id'])}>" if event and event["actor_id"] else "SentriX"
        reason = str(event["details"] or "") if event else ""
        try:
            url = await ticket_transcript_links.publish_link(
                bot, ticket_id=self.ticket_id, guild_id=guild.id,
                channel_id=int(row["channel_id"]), channel_name=str(archived["channel_name"]),
                transcript_text=str(archived["transcript_text"]),
                viewer_id=user.id, closer_name=closer, close_reason=reason,
            )
        except Exception:
            logger.exception("Lien staff indisponible pour ticket #%s", self.ticket_id)
            text = language_runtime.text_for_language(
                lang, "Impossible de créer le lien privé. Réessayez.",
                "Unable to create a private link. Please try again."
            )
            return await interaction.followup.send(text, ephemeral=True)

        view = discord.ui.View(timeout=300)
        view.add_item(discord.ui.Button(
            style=discord.ButtonStyle.link,
            label=language_runtime.text_for_language(lang, "Ouvrir la transcription", "Open transcript"),
            url=url,
        ))
        text = language_runtime.text_for_language(
            lang,
            "Votre lien personnel de transcription est prêt (validité : 90 jours). "
            "Ne le partagez pas.",
            "Your private transcript link is ready (valid for 90 days). Do not share it.",
        )
        await interaction.followup.send(text, view=view, ephemeral=True)
