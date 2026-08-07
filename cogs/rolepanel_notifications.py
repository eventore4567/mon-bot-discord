"""Panneau de rôles de notifications SentriX.

Remplace proprement l'ancien +rolepanel dès qu'il est chargé :
- +rolepanel crée/emploie des rôles de notifications standards ;
- les membres choisissent eux-mêmes leurs notifications dans un menu ;
- les panneaux sont persistants après redémarrage ;
- +rolepanel-refresh reconstruit le dernier panneau du serveur.
"""
from __future__ import annotations

import json
import logging
import time

import discord
from discord.ext import commands

logger = logging.getLogger("bot.rolepanel.notifications")

DEFAULT_NOTIFICATION_ROLES = (
    ("Notifications annonces", "Recevoir les annonces importantes du serveur."),
    ("Notifications événements", "Être prévenu lors des événements et animations."),
    ("Notifications giveaways", "Être prévenu lors des giveaways et concours."),
    ("Notifications mises à jour", "Recevoir les nouveautés et mises à jour du serveur."),
    ("Notifications concours", "Être prévenu lors des concours spéciaux."),
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notification_role_panels (
    message_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    role_ids_json TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL
)
"""

_INSTALLED = False
_COG_NAME = "NotificationRolePanels"


def _panel_embed(guild: discord.Guild, role_ids: list[int]) -> discord.Embed:
    roles = [guild.get_role(role_id) for role_id in role_ids]
    roles = [role for role in roles if role is not None]
    lines = [f"● {role.mention}" for role in roles]
    e = discord.Embed(
        title="Notifications",
        description=(
            "Choisis les notifications que tu veux recevoir avec le menu ci-dessous.\n"
            "Tu peux modifier tes choix à tout moment."
        ),
        color=0x7C6CFF,
    )
    e.add_field(
        name="Rôles disponibles",
        value="\n".join(lines) if lines else "Aucun rôle disponible.",
        inline=False,
    )
    e.set_footer(text="SentriX • Rôles de notifications")
    return e


class NotificationRoleSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild, role_ids: list[int]):
        options: list[discord.SelectOption] = []
        for role_id in role_ids[:25]:
            role = guild.get_role(role_id)
            if role is None:
                continue
            description = next(
                (desc for name, desc in DEFAULT_NOTIFICATION_ROLES if name == role.name),
                "Activer ou désactiver cette notification.",
            )
            options.append(
                discord.SelectOption(
                    label=role.name[:100],
                    value=str(role.id),
                    description=description[:100],
                )
            )
        super().__init__(
            placeholder="Choisis tes notifications…",
            min_values=0,
            max_values=max(1, len(options)),
            options=options or [discord.SelectOption(label="Aucun rôle disponible", value="0")],
            custom_id="sentrix:notification-roles",
            disabled=not bool(options),
        )
        self.role_ids = [int(option.value) for option in options]

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "Ce panneau fonctionne uniquement dans un serveur.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        member = interaction.user
        guild = interaction.guild
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            return await interaction.followup.send(
                "SentriX a besoin de la permission **Gérer les rôles**.", ephemeral=True
            )

        selected_ids = {int(value) for value in self.values if value.isdigit() and value != "0"}
        managed_ids = set(self.role_ids)
        current_ids = {role.id for role in member.roles if role.id in managed_ids}

        add_ids = selected_ids - current_ids
        remove_ids = current_ids - selected_ids
        blocked: list[str] = []
        add_roles: list[discord.Role] = []
        remove_roles: list[discord.Role] = []

        for role_id in add_ids:
            role = guild.get_role(role_id)
            if role is None:
                continue
            if role >= bot_member.top_role or role.managed:
                blocked.append(role.name)
                continue
            add_roles.append(role)

        for role_id in remove_ids:
            role = guild.get_role(role_id)
            if role is None:
                continue
            if role >= bot_member.top_role or role.managed:
                blocked.append(role.name)
                continue
            remove_roles.append(role)

        try:
            if add_roles:
                await member.add_roles(*add_roles, reason="Panneau de notifications SentriX")
            if remove_roles:
                await member.remove_roles(*remove_roles, reason="Panneau de notifications SentriX")
        except discord.Forbidden:
            return await interaction.followup.send(
                "Je ne peux pas modifier un ou plusieurs rôles. Place le rôle SentriX au-dessus des rôles de notifications.",
                ephemeral=True,
            )
        except discord.HTTPException:
            return await interaction.followup.send(
                "Discord a refusé la modification. Réessaie dans quelques secondes.", ephemeral=True
            )

        text = "Tes notifications ont été mises à jour."
        if blocked:
            text += " Certains rôles sont placés au-dessus de SentriX : " + ", ".join(blocked)
        await interaction.followup.send(text, ephemeral=True)


class NotificationRoleView(discord.ui.View):
    def __init__(self, guild: discord.Guild, role_ids: list[int]):
        super().__init__(timeout=None)
        self.add_item(NotificationRoleSelect(guild, role_ids))


class NotificationRolePanels(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _ensure_roles(self, guild: discord.Guild) -> list[discord.Role]:
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            raise commands.BotMissingPermissions(["manage_roles"])

        roles: list[discord.Role] = []
        for name, _description in DEFAULT_NOTIFICATION_ROLES:
            role = discord.utils.get(guild.roles, name=name)
            if role is None:
                role = await guild.create_role(
                    name=name,
                    permissions=discord.Permissions.none(),
                    mentionable=False,
                    reason="Création du panneau de notifications SentriX",
                )
            roles.append(role)
        return roles

    async def _save_panel(self, message: discord.Message, creator_id: int, role_ids: list[int]):
        await self.bot.db.execute(
            "INSERT INTO notification_role_panels "
            "(message_id, guild_id, channel_id, role_ids_json, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(message_id) DO UPDATE SET role_ids_json=excluded.role_ids_json",
            (
                message.id,
                message.guild.id,
                message.channel.id,
                json.dumps(role_ids),
                creator_id,
                int(time.time()),
            ),
        )

    @commands.command(
        name="rolepanel",
        aliases=["role-panel", "roles-notifs", "notifs-roles"],
        help="Créer un panneau permettant aux membres de choisir leurs rôles de notifications.",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def rolepanel(self, ctx: commands.Context):
        """Crée les rôles de notifications manquants puis publie le panneau."""
        try:
            roles = await self._ensure_roles(ctx.guild)
        except commands.BotMissingPermissions:
            return await ctx.send(
                "SentriX a besoin de la permission **Gérer les rôles** pour créer le panneau."
            )
        except discord.Forbidden:
            return await ctx.send(
                "Je ne peux pas créer les rôles. Vérifie la permission **Gérer les rôles**."
            )

        role_ids = [role.id for role in roles]
        view = NotificationRoleView(ctx.guild, role_ids)
        message = await ctx.send(embed=_panel_embed(ctx.guild, role_ids), view=view)
        await self._save_panel(message, ctx.author.id, role_ids)
        self.bot.add_view(NotificationRoleView(ctx.guild, role_ids), message_id=message.id)

    @commands.command(
        name="rolepanel-refresh",
        aliases=["refresh-rolepanel"],
        help="Mettre à jour le dernier panneau de rôles de notifications du serveur.",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def rolepanel_refresh(self, ctx: commands.Context, message_id: int | None = None):
        if message_id is None:
            row = await self.bot.db.fetchone(
                "SELECT * FROM notification_role_panels WHERE guild_id = ? ORDER BY created_at DESC LIMIT 1",
                (ctx.guild.id,),
            )
        else:
            row = await self.bot.db.fetchone(
                "SELECT * FROM notification_role_panels WHERE guild_id = ? AND message_id = ?",
                (ctx.guild.id, message_id),
            )
        if not row:
            return await ctx.send("Aucun panneau de notifications SentriX n'a été trouvé sur ce serveur.")

        try:
            role_ids = [int(value) for value in json.loads(row["role_ids_json"])]
        except Exception:
            role_ids = []

        # Recrée automatiquement les rôles standards supprimés, puis met à jour la liste.
        roles = await self._ensure_roles(ctx.guild)
        standard_ids = [role.id for role in roles]
        role_ids = list(dict.fromkeys([*role_ids, *standard_ids]))
        role_ids = [role_id for role_id in role_ids if ctx.guild.get_role(role_id) is not None][:25]

        channel = ctx.guild.get_channel(int(row["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return await ctx.send("Le salon du panneau n'existe plus.")
        try:
            message = await channel.fetch_message(int(row["message_id"]))
        except discord.NotFound:
            return await ctx.send("Le message du panneau a été supprimé. Relance `+rolepanel`.")
        except discord.Forbidden:
            return await ctx.send("SentriX ne peut pas accéder au message du panneau.")

        view = NotificationRoleView(ctx.guild, role_ids)
        await message.edit(embed=_panel_embed(ctx.guild, role_ids), view=view)
        await self._save_panel(message, ctx.author.id, role_ids)
        self.bot.add_view(NotificationRoleView(ctx.guild, role_ids), message_id=message.id)
        await ctx.send("Le panneau de notifications a été mis à jour.")


async def install(bot: commands.Bot) -> None:
    """Installe le nouveau rolepanel quand l'ancien est présent, sans doublon de commande."""
    global _INSTALLED
    if _INSTALLED:
        return

    old = bot.get_command("rolepanel")
    if old is None:
        return

    # Prépare la persistance avant de remplacer les anciennes commandes.
    await bot.db.execute(_SCHEMA)
    await bot.db.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_role_panels_guild "
        "ON notification_role_panels (guild_id, created_at)"
    )

    bot.remove_command("rolepanel")
    if bot.get_command("rolepanel-refresh") is not None:
        bot.remove_command("rolepanel-refresh")

    if bot.get_cog(_COG_NAME) is None:
        await bot.add_cog(NotificationRolePanels(bot))

    # Restaure les panneaux existants après un redémarrage Railway.
    try:
        rows = await bot.db.fetchall("SELECT * FROM notification_role_panels")
        for row in rows:
            guild = bot.get_guild(int(row["guild_id"]))
            if guild is None:
                continue
            try:
                role_ids = [int(value) for value in json.loads(row["role_ids_json"])]
            except Exception:
                continue
            role_ids = [role_id for role_id in role_ids if guild.get_role(role_id) is not None][:25]
            if not role_ids:
                continue
            bot.add_view(NotificationRoleView(guild, role_ids), message_id=int(row["message_id"]))
    except Exception:
        logger.exception("Restauration des panneaux de notifications impossible.")

    _INSTALLED = True
    logger.info("+rolepanel mis à jour avec les rôles de notifications.")
