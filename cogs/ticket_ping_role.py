"""Rôle global à ping lors de l'ouverture d'un ticket.

Le réglage est volontairement séparé du rôle staff de chaque type de ticket : choisir un
rôle à notifier ne modifie jamais les permissions du salon. Si aucun rôle global valide
n'est configuré, le comportement historique de ticket_types.mention_staff reste inchangé.
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


async def _resolve_ping_role(bot: commands.Bot, guild: discord.Guild) -> discord.Role | None:
    """Retourne uniquement un rôle encore utilisable.

    Un rôle supprimé/managed ne doit surtout pas désactiver le ping staff historique :
    dans ce cas on nettoie le réglage obsolète et on revient au comportement normal.
    """
    role_id = await get_ticket_ping_role_id(bot, guild.id)
    if not role_id:
        return None

    role = guild.get_role(role_id)
    if role is not None and not role.is_default() and not role.managed:
        return role

    logger.warning(
        "Rôle ping tickets invalide (%s) sur %s ; retour au rôle staff du type.",
        role_id,
        guild.id,
    )
    try:
        await set_ticket_ping_role_id(bot, guild.id, None)
    except Exception:
        logger.exception(
            "Impossible de nettoyer le rôle ping tickets invalide %s sur %s.",
            role_id,
            guild.id,
        )
    return None


def _ticket_value(ticket_type, key: str, default=None):
    try:
        return ticket_type[key]
    except (KeyError, TypeError, IndexError):
        return default


async def _fallback_staff_ping(
    channel: discord.TextChannel,
    guild: discord.Guild,
    ticket_type,
) -> None:
    """Best effort : si le ping global échoue, prévenir quand même le staff historique."""
    if not _ticket_value(ticket_type, "mention_staff", 0):
        return
    staff_role_id = _ticket_value(ticket_type, "staff_role_id")
    staff_role = guild.get_role(int(staff_role_id)) if staff_role_id else None
    if staff_role is None or staff_role.is_default():
        return
    try:
        await channel.send(
            f"🔔 {staff_role.mention} — nouveau ticket à prendre en charge.",
            allowed_mentions=discord.AllowedMentions(
                everyone=False,
                users=False,
                roles=[staff_role],
                replied_user=False,
            ),
        )
    except discord.HTTPException:
        logger.exception(
            "Le ping global ET le ping staff de secours ont échoué dans %s (guild=%s).",
            channel.id,
            guild.id,
        )


def install_ticket_runtime(bot: commands.Bot) -> None:
    """Ajoute le ping choisi sans rendre le moteur de tickets dépendant de cette option."""
    global _RUNTIME_INSTALLED
    if _RUNTIME_INSTALLED:
        return

    from . import tickets

    original_create_ticket = tickets.Tickets.create_ticket

    async def create_ticket_with_configured_ping(self, interaction, ticket_type, answers):
        guild = interaction.guild
        role: discord.Role | None = None
        before_id = 0

        # Cette fonctionnalité est optionnelle : une panne de son réglage ne doit jamais
        # empêcher l'ouverture du ticket principal.
        if guild:
            try:
                role = await _resolve_ping_role(self.bot, guild)
                if role is not None:
                    before = await self.bot.db.fetchone(
                        "SELECT COALESCE(MAX(id), 0) AS last_id FROM tickets WHERE guild_id = ?",
                        (guild.id,),
                    )
                    before_id = int(before["last_id"] if before else 0)
            except Exception:
                logger.exception(
                    "Impossible de préparer le rôle ping tickets sur %s ; fallback staff conservé.",
                    guild.id,
                )
                role = None

        # On coupe le ping staff d'origine UNIQUEMENT si le rôle global existe vraiment et
        # que l'on est prêt à retrouver le ticket créé ensuite. Un rôle supprimé ne peut donc
        # plus provoquer un ticket sans aucune notification staff.
        effective_type = ticket_type
        staff_ping_suppressed = False
        if role is not None:
            try:
                effective_type = dict(ticket_type)
                effective_type["mention_staff"] = 0
                staff_ping_suppressed = True
            except Exception:
                logger.exception("Impossible de copier le type de ticket ; ping staff d'origine conservé.")
                effective_type = ticket_type

        result = await original_create_ticket(self, interaction, effective_type, answers)

        if not guild or role is None:
            return result

        try:
            created = await self.bot.db.fetchone(
                """
                SELECT id, channel_id FROM tickets
                WHERE guild_id = ? AND user_id = ? AND type_id = ? AND id > ?
                ORDER BY id DESC LIMIT 1
                """,
                (guild.id, interaction.user.id, _ticket_value(ticket_type, "id"), before_id),
            )
            if not created:
                logger.warning(
                    "Ticket créé mais introuvable pour le ping global (guild=%s, user=%s, type=%s).",
                    guild.id,
                    interaction.user.id,
                    _ticket_value(ticket_type, "id"),
                )
                return result

            channel = guild.get_channel(int(created["channel_id"]))
            if not isinstance(channel, discord.TextChannel):
                logger.warning(
                    "Salon du ticket #%s introuvable pour le ping global (guild=%s).",
                    created["id"],
                    guild.id,
                )
                return result

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
                "Impossible de ping le rôle %s à l'ouverture d'un ticket sur %s.",
                role.id,
                guild.id,
            )
            if staff_ping_suppressed and 'channel' in locals() and isinstance(channel, discord.TextChannel):
                await _fallback_staff_ping(channel, guild, ticket_type)
        except Exception:
            # Le ticket existe déjà à ce stade : ne jamais transformer un souci de notification
            # facultative en erreur visible pour le membre.
            logger.exception(
                "Erreur non bloquante après création du ticket lors du ping global (guild=%s).",
                guild.id,
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

        try:
            role_id = await get_ticket_ping_role_id(self.bot, self.guild_id)
        except Exception:
            logger.exception("Impossible de lire le rôle ping depuis +setup (guild=%s).", self.guild_id)
            role_id = None
        guild = self._guild()
        role = guild.get_role(role_id) if guild and role_id else None
        if role is not None and (role.is_default() or role.managed):
            role = None
        embed.add_field(
            name="🔔 Rôle ping à l'ouverture",
            value=role.mention if role else "*Aucun rôle — comportement staff normal*",
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
            if role.id == interaction.guild.default_role.id or role.managed:
                return await interaction.response.send_message(
                    "Ce rôle ne peut pas être utilisé pour les notifications de tickets.",
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
