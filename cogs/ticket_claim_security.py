"""Sécurise les boutons staff et la confidentialité des tickets pris en charge."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("bot.tickets.claim-security")
_INSTALLED = False

_STAFF_ONLY_KEYS = {"claim", "unclaim", "add", "remove", "rename", "transfer", "note", "bump"}


async def _ticket_type(cog, ticket):
    type_id = ticket["type_id"] if ticket else None
    if not type_id:
        return None
    try:
        return await cog.get_type(type_id)
    except Exception:
        return None


async def _authorized_staff(cog, interaction: discord.Interaction, ticket, key: str) -> bool:
    guild = interaction.guild
    member = interaction.user
    if guild is None or not isinstance(member, discord.Member):
        return False
    if member.id == guild.owner_id or member.guild_permissions.administrator:
        return True

    from . import tickets

    settings = await tickets.get_button_settings(cog.bot, guild.id)
    cfg = settings.get(key, {})
    configured_role_id = cfg.get("role_id")
    if configured_role_id:
        configured_role = guild.get_role(int(configured_role_id))
        return bool(configured_role and configured_role in member.roles)

    ticket_type = await _ticket_type(cog, ticket)
    staff_role_id = ticket_type["staff_role_id"] if ticket_type else None
    if not staff_role_id:
        return False
    staff_role = guild.get_role(int(staff_role_id))
    return bool(staff_role and staff_role in member.roles)


async def _set_staff_role_visibility(cog, channel: discord.TextChannel, ticket, *, visible: bool) -> None:
    ticket_type = await _ticket_type(cog, ticket)
    staff_role_id = ticket_type["staff_role_id"] if ticket_type else None
    if not staff_role_id:
        return
    staff_role = channel.guild.get_role(int(staff_role_id))
    if staff_role is None:
        return

    overwrite = channel.overwrites_for(staff_role)
    overwrite.view_channel = visible
    overwrite.send_messages = visible
    overwrite.read_message_history = visible
    try:
        await channel.set_permissions(
            staff_role,
            overwrite=overwrite,
            reason=("Ticket pris en charge : accès réservé" if not visible else "Prise en charge annulée : accès staff rétabli"),
        )
    except discord.HTTPException:
        logger.exception("Impossible de modifier l'accès du rôle staff au ticket %s.", ticket["id"])


async def _grant_claimant(channel: discord.TextChannel, member: discord.Member) -> None:
    overwrite = channel.overwrites_for(member)
    overwrite.view_channel = True
    overwrite.send_messages = True
    overwrite.read_message_history = True
    overwrite.attach_files = True
    await channel.set_permissions(member, overwrite=overwrite, reason="Ticket pris en charge")


async def _remove_claimant_override(channel: discord.TextChannel, member: discord.Member | None, owner_id: int) -> None:
    if member is None or member.id == owner_id or member.guild_permissions.administrator:
        return
    try:
        await channel.set_permissions(member, overwrite=None, reason="Fin de prise en charge du ticket")
    except discord.HTTPException:
        pass


def install(bot: commands.Bot) -> None:
    del bot
    global _INSTALLED
    if _INSTALLED:
        return

    from . import tickets

    original_handle = tickets.Tickets.handle_control_button

    async def secure_handle_control_button(self, interaction: discord.Interaction, key: str):
        ticket = await self.get_ticket_by_channel(interaction.channel.id)
        if not ticket:
            return await original_handle(self, interaction, key)

        if key in _STAFF_ONLY_KEYS:
            if not await _authorized_staff(self, interaction, ticket, key):
                return await interaction.response.send_message(
                    embed=tickets.embeds.error(
                        "Ce bouton est réservé au staff autorisé de ce ticket."
                    ),
                    ephemeral=True,
                )
        elif key == "close":
            # Le créateur peut fermer son propre ticket. Pour tous les autres membres,
            # il faut être staff autorisé.
            if interaction.user.id != ticket["user_id"] and not await _authorized_staff(self, interaction, ticket, key):
                return await interaction.response.send_message(
                    embed=tickets.embeds.error("Vous n'êtes pas autorisé à fermer ce ticket."),
                    ephemeral=True,
                )

        return await original_handle(self, interaction, key)

    async def secure_claim(self, interaction: discord.Interaction, ticket):
        channel = interaction.channel
        guild = interaction.guild
        member = interaction.user
        if not isinstance(channel, discord.TextChannel) or guild is None or not isinstance(member, discord.Member):
            return await interaction.response.send_message(
                embed=tickets.embeds.error("Impossible de prendre en charge ce ticket."), ephemeral=True
            )

        current_id = ticket["claimed_by"]
        if current_id:
            if int(current_id) == member.id:
                return await interaction.response.send_message(
                    embed=tickets.embeds.warning("Vous avez déjà pris en charge ce ticket."), ephemeral=True
                )
            if not member.guild_permissions.administrator and member.id != guild.owner_id:
                current = guild.get_member(int(current_id))
                return await interaction.response.send_message(
                    embed=tickets.embeds.warning(
                        f"Ce ticket est déjà pris en charge par {current.mention if current else 'un autre membre du staff'}."
                    ),
                    ephemeral=True,
                )

        await interaction.response.defer()

        old_member = guild.get_member(int(current_id)) if current_id else None
        if old_member and old_member.id != member.id:
            await _remove_claimant_override(channel, old_member, int(ticket["user_id"]))

        # Le rôle staff général est masqué après le claim. Les Administrateurs Discord
        # continuent d'accéder au salon grâce à leur permission Administrateur, le créateur
        # garde son overwrite individuel et le membre qui claim reçoit un overwrite dédié.
        await _set_staff_role_visibility(self, channel, ticket, visible=False)
        try:
            await _grant_claimant(channel, member)
        except discord.Forbidden:
            return await interaction.followup.send(
                embed=tickets.embeds.error("SentriX n'a pas la permission de modifier les accès de ce ticket."),
                ephemeral=True,
            )

        await self.bot.db.execute(
            "UPDATE tickets SET claimed_by = ?, last_activity_at = ? WHERE id = ?",
            (member.id, tickets.now(), ticket["id"]),
        )
        await interaction.followup.send(
            embed=tickets.embeds.success(
                f"{member.mention} a pris en charge ce ticket. L'accès est maintenant réservé au créateur, au membre en charge et aux Administrateurs."
            )
        )

    async def secure_unclaim(self, interaction: discord.Interaction, ticket):
        guild = interaction.guild
        channel = interaction.channel
        member = interaction.user
        if guild is None or not isinstance(channel, discord.TextChannel) or not isinstance(member, discord.Member):
            return await interaction.response.send_message(embed=tickets.embeds.error("Action impossible."), ephemeral=True)

        current_id = ticket["claimed_by"]
        if not current_id:
            return await interaction.response.send_message(
                embed=tickets.embeds.warning("Ce ticket n'est pas actuellement pris en charge."), ephemeral=True
            )
        if int(current_id) != member.id and not member.guild_permissions.administrator and member.id != guild.owner_id:
            return await interaction.response.send_message(
                embed=tickets.embeds.error("Seul le membre en charge ou un Administrateur peut abandonner ce ticket."),
                ephemeral=True,
            )

        await interaction.response.defer()
        claimant = guild.get_member(int(current_id))
        await _remove_claimant_override(channel, claimant, int(ticket["user_id"]))
        await _set_staff_role_visibility(self, channel, ticket, visible=True)
        await self.bot.db.execute(
            "UPDATE tickets SET claimed_by = NULL, last_activity_at = ? WHERE id = ?",
            (tickets.now(), ticket["id"]),
        )
        await interaction.followup.send(embed=tickets.embeds.success("Prise en charge annulée. L'accès du rôle staff a été rétabli."))

    tickets.Tickets.handle_control_button = secure_handle_control_button
    tickets.Tickets.btn_claim = secure_claim
    tickets.Tickets.btn_unclaim = secure_unclaim
    _INSTALLED = True
    logger.info("Sécurité des prises en charge de tickets activée.")
