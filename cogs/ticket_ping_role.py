"""Rôle global à ping lors de l'ouverture d'un ticket.

Le réglage est volontairement séparé du rôle staff de chaque type de ticket : choisir un
rôle à notifier ne modifie jamais les permissions du salon. Si aucun rôle global n'est
configuré, le comportement historique de ticket_types.mention_staff reste inchangé.
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("bot.ticket-ping-role")
_RUNTIME_INSTALLED = False
_SETUP_INSTALLED = False


async def _ensure_table(bot: commands.Bot) -> None:
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_ping_settings (
            guild_id INTEGER PRIMARY KEY,
            role_id INTEGER,
            updated_at INTEGER NOT NULL DEFAULT 0
        )
        """
    )


async def get_ticket_ping_role_id(bot: commands.Bot, guild_id: int) -> int | None:
    await _ensure_table(bot)
    row = await bot.db.fetchone(
        "SELECT role_id FROM ticket_ping_settings WHERE guild_id = ?",
        (guild_id,),
    )
    if not row or not row["role_id"]:
        return None
    return int(row["role_id"])


async def set_ticket_ping_role_id(bot: commands.Bot, guild_id: int, role_id: int | None) -> None:
    from database.db import now

    await _ensure_table(bot)
    await bot.db.execute(
        """
        INSERT INTO ticket_ping_settings (guild_id, role_id, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            role_id = excluded.role_id,
            updated_at = excluded.updated_at
        """,
        (guild_id, role_id, now()),
    )


def install_ticket_runtime(bot: commands.Bot) -> None:
    """Ajoute le ping choisi sans réécrire le moteur de création de tickets."""
    global _RUNTIME_INSTALLED
    if _RUNTIME_INSTALLED:
        return

    from . import tickets

    original_create_ticket = tickets.Tickets.create_ticket

    async def create_ticket_with_configured_ping(self, interaction, ticket_type, answers):
        guild = interaction.guild
        role_id = await get_ticket_ping_role_id(self.bot, guild.id) if guild else None

        # Quand un rôle global est choisi, c'est lui qui devient l'unique rôle notifié.
        # Le rôle staff du type conserve néanmoins ses permissions d'accès au salon.
        effective_type = ticket_type
        if role_id:
            try:
                effective_type = dict(ticket_type)
                effective_type["mention_staff"] = 0
            except Exception:
                effective_type = ticket_type

        before = await self.bot.db.fetchone(
            "SELECT COALESCE(MAX(id), 0) AS last_id FROM tickets WHERE guild_id = ?",
            (guild.id,),
        ) if guild else None
        before_id = int(before["last_id"] if before else 0)

        result = await original_create_ticket(self, interaction, effective_type, answers)

        if not guild or not role_id:
            return result

        role = guild.get_role(role_id)
        if role is None or role.is_default():
            return result

        created = await self.bot.db.fetchone(
            """
            SELECT id, channel_id FROM tickets
            WHERE guild_id = ? AND user_id = ? AND type_id = ? AND id > ?
            ORDER BY id DESC LIMIT 1
            """,
            (guild.id, interaction.user.id, ticket_type["id"], before_id),
        )
        if not created:
            return result

        channel = guild.get_channel(int(created["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return result

        try:
            await channel.send(
                f"🔔 {role.mention} — nouveau ticket à prendre en charge.",
                allowed_mentions=discord.AllowedMentions(
                    everyone=False,
                    users=False,
                    roles=[role],
                    replied_user=False,
                ),
            )
        except discord.HTTPException:
            logger.exception(
                "Impossible de ping le rôle %s à l'ouverture du ticket %s sur %s.",
                role.id, created["id"], guild.id,
            )
        return result

    tickets.Tickets.create_ticket = create_ticket_with_configured_ping
    _RUNTIME_INSTALLED = True
    logger.info("Rôle de ping global des tickets activé.")


def install_setup_ui(bot: commands.Bot) -> None:
    """Ajoute le choix du rôle directement dans +setup > Tickets."""
    global _SETUP_INSTALLED
    if _SETUP_INSTALLED:
        return

    from . import configuration

    original_build_embed = configuration.SetupView.build_embed
    original_render_page = configuration.SetupView.render_page

    async def build_embed(self):
        embed = await original_build_embed(self)
        if self.page < 0:
            return embed
        try:
            step = configuration.SETUP_STEPS[self.page]
        except (IndexError, TypeError):
            return embed
        if step["key"] != "tickets":
            return embed

        role_id = await get_ticket_ping_role_id(self.bot, self.guild_id)
        guild = self._guild()
        role = guild.get_role(role_id) if guild and role_id else None
        embed.add_field(
            name="🔔 Rôle ping à l'ouverture",
            value=role.mention if role else "*Aucun rôle — aucun ping global*",
            inline=False,
        )
        return embed

    def render_page(self):
        original_render_page(self)
        if self.page < 0:
            return
        try:
            step = configuration.SETUP_STEPS[self.page]
        except (IndexError, TypeError):
            return
        if step["key"] != "tickets":
            return

        role_select = discord.ui.RoleSelect(
            placeholder="🔔 Choisir le rôle à ping à chaque nouveau ticket",
            min_values=1,
            max_values=1,
            row=1,
        )

        async def role_callback(interaction: discord.Interaction):
            role = role_select.values[0]
            if role.id == interaction.guild.default_role.id:
                return await interaction.response.send_message(
                    "@everyone ne peut pas être utilisé comme rôle de ping des tickets.",
                    ephemeral=True,
                )
            await set_ticket_ping_role_id(self.bot, self.guild_id, role.id)
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)

        role_select.callback = role_callback
        self.add_item(role_select)

        clear_button = discord.ui.Button(
            label="Retirer le rôle ping",
            emoji="🔕",
            style=discord.ButtonStyle.secondary,
            row=2,
        )

        async def clear_callback(interaction: discord.Interaction):
            await set_ticket_ping_role_id(self.bot, self.guild_id, None)
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)

        clear_button.callback = clear_callback
        self.add_item(clear_button)

    configuration.SetupView.build_embed = build_embed
    configuration.SetupView.render_page = render_page
    _SETUP_INSTALLED = True
    logger.info("Choix du rôle de ping ajouté à +setup > Tickets.")
