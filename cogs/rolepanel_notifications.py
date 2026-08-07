"""Panneau de rôles de notifications SentriX.

Le panneau public reste compact. Chaque membre ouvre un menu privé qui n'affiche que les
rôles qu'il peut encore ajouter ou retirer. Dès qu'un rôle est pris, il disparaît donc du
menu personnel sans modifier le panneau pour les autres membres.
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


def _role_description(role_name: str) -> str:
    return next(
        (desc for name, desc in DEFAULT_NOTIFICATION_ROLES if name == role_name),
        "Activer ou désactiver cette notification.",
    )


def _panel_embed(guild: discord.Guild, role_ids: list[int]) -> discord.Embed:
    roles = [guild.get_role(role_id) for role_id in role_ids]
    roles = [role for role in roles if role is not None]
    e = discord.Embed(
        title="Notifications",
        description=(
            "Choisis uniquement les notifications que tu veux recevoir.\n\n"
            "Clique sur **Ajouter des notifications** pour prendre des rôles ou sur "
            "**Retirer des notifications** pour enlever ceux que tu ne veux plus."
        ),
        color=0x7C6CFF,
    )
    e.add_field(
        name="Disponibles",
        value=f"**{len(roles)}** rôles de notifications configurés.",
        inline=True,
    )
    e.add_field(
        name="Fonctionnement",
        value="Tes choix sont privés et le panneau reste identique pour les autres membres.",
        inline=False,
    )
    e.set_footer(text="SentriX • Rôles de notifications")
    return e


def _manageable_roles(guild: discord.Guild, role_ids: list[int]) -> list[discord.Role]:
    bot_member = guild.me
    if bot_member is None:
        return []
    roles: list[discord.Role] = []
    for role_id in role_ids[:25]:
        role = guild.get_role(role_id)
        if role is None or role.managed or role >= bot_member.top_role:
            continue
        roles.append(role)
    return roles


class PersonalNotificationSelect(discord.ui.Select):
    def __init__(
        self,
        guild: discord.Guild,
        member: discord.Member,
        role_ids: list[int],
        *,
        mode: str,
    ):
        all_roles = _manageable_roles(guild, role_ids)
        member_role_ids = {role.id for role in member.roles}
        if mode == "add":
            roles = [role for role in all_roles if role.id not in member_role_ids]
            placeholder = "Choisis les notifications à ajouter…"
        else:
            roles = [role for role in all_roles if role.id in member_role_ids]
            placeholder = "Choisis les notifications à retirer…"

        options = [
            discord.SelectOption(
                label=role.name[:100],
                value=str(role.id),
                description=_role_description(role.name)[:100],
            )
            for role in roles[:25]
        ]
        if not options:
            options = [
                discord.SelectOption(
                    label="Aucune notification disponible",
                    value="0",
                    description=(
                        "Tu as déjà tous les rôles." if mode == "add"
                        else "Tu n'as aucun rôle de notification."
                    ),
                )
            ]
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=max(1, len(options)),
            options=options,
            custom_id=f"sentrix:notification-private:{mode}",
            disabled=options[0].value == "0",
        )
        self.role_ids = list(role_ids)
        self.mode = mode

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "Ce panneau fonctionne uniquement dans un serveur.", ephemeral=True
            )

        member = interaction.user
        guild = interaction.guild
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            return await interaction.response.send_message(
                "SentriX a besoin de la permission **Gérer les rôles**.", ephemeral=True
            )

        selected_ids = [int(value) for value in self.values if value.isdigit() and value != "0"]
        roles: list[discord.Role] = []
        for role_id in selected_ids:
            role = guild.get_role(role_id)
            if role is None or role.managed or role >= bot_member.top_role:
                continue
            roles.append(role)

        if not roles:
            return await interaction.response.edit_message(
                content="Aucun rôle modifiable n'a été sélectionné.",
                view=PersonalNotificationView(guild, member, self.role_ids, mode=self.mode),
            )

        try:
            if self.mode == "add":
                await member.add_roles(*roles, reason="Panneau de notifications SentriX")
                text = "Ajouté : " + ", ".join(role.name for role in roles)
            else:
                await member.remove_roles(*roles, reason="Panneau de notifications SentriX")
                text = "Retiré : " + ", ".join(role.name for role in roles)
        except discord.Forbidden:
            return await interaction.response.edit_message(
                content="SentriX ne peut pas modifier ces rôles. Place son rôle au-dessus des rôles de notifications.",
                view=None,
            )
        except discord.HTTPException:
            return await interaction.response.edit_message(
                content="Discord a refusé la modification. Réessaie dans quelques secondes.",
                view=PersonalNotificationView(guild, member, self.role_ids, mode=self.mode),
            )

        # On reconstruit immédiatement le menu : les rôles qui viennent d'être ajoutés
        # disparaissent de la liste Ajouter, et ceux retirés disparaissent de la liste Retirer.
        await interaction.response.edit_message(
            content=f"✅ {text}",
            view=PersonalNotificationView(guild, member, self.role_ids, mode=self.mode),
        )


class PersonalNotificationView(discord.ui.View):
    def __init__(
        self,
        guild: discord.Guild,
        member: discord.Member,
        role_ids: list[int],
        *,
        mode: str,
    ):
        super().__init__(timeout=180)
        self.add_item(PersonalNotificationSelect(guild, member, role_ids, mode=mode))


class NotificationRoleView(discord.ui.View):
    def __init__(self, guild: discord.Guild, role_ids: list[int]):
        super().__init__(timeout=None)
        self.guild_id = guild.id
        self.role_ids = list(role_ids)

    @discord.ui.button(
        label="Ajouter des notifications",
        style=discord.ButtonStyle.primary,
        custom_id="sentrix:notification-open:add",
    )
    async def add_notifications(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)
        await interaction.response.send_message(
            "Sélectionne les notifications que tu veux recevoir. Les rôles déjà pris ne sont pas affichés.",
            view=PersonalNotificationView(interaction.guild, interaction.user, self.role_ids, mode="add"),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Retirer des notifications",
        style=discord.ButtonStyle.secondary,
        custom_id="sentrix:notification-open:remove",
    )
    async def remove_notifications(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)
        await interaction.response.send_message(
            "Sélectionne les notifications que tu veux retirer. Seuls tes rôles actuels sont affichés.",
            view=PersonalNotificationView(interaction.guild, interaction.user, self.role_ids, mode="remove"),
            ephemeral=True,
        )


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
        try:
            roles = await self._ensure_roles(ctx.guild)
        except commands.BotMissingPermissions:
            return await ctx.send("SentriX a besoin de la permission **Gérer les rôles** pour créer le panneau.")
        except discord.Forbidden:
            return await ctx.send("Je ne peux pas créer les rôles. Vérifie la permission **Gérer les rôles**.")

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
    global _INSTALLED
    if _INSTALLED:
        return

    old = bot.get_command("rolepanel")
    if old is None:
        return

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

    # Restaure ET migre les anciens panneaux : le gros menu déroulant est remplacé par
    # deux boutons compacts au redémarrage, sans demander de recréer le message.
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
            view = NotificationRoleView(guild, role_ids)
            bot.add_view(view, message_id=int(row["message_id"]))
            channel = guild.get_channel(int(row["channel_id"]))
            if isinstance(channel, discord.TextChannel):
                try:
                    message = await channel.fetch_message(int(row["message_id"]))
                    await message.edit(embed=_panel_embed(guild, role_ids), view=view)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
    except Exception:
        logger.exception("Restauration des panneaux de notifications impossible.")

    _INSTALLED = True
    logger.info("+rolepanel personnel et compact activé.")
