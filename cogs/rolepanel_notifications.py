"""Panneau de rôles de notifications SentriX.

Le panneau public reste compact. Chaque membre ouvre un menu privé qui n'affiche que les
rôles qu'il peut encore ajouter ou retirer. Les vues publiques sont persistantes et sont
enregistrées globalement afin que les anciens panneaux continuent de répondre après un
redémarrage, même si leur ligne SQL a été nettoyée ou migrée.
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


def _catalog_role_ids(guild: discord.Guild) -> list[int]:
    result: list[int] = []
    for name, _description in DEFAULT_NOTIFICATION_ROLES:
        role = discord.utils.get(guild.roles, name=name)
        if role is not None and role.id not in result:
            result.append(role.id)
    return result[:25]


def _merge_role_ids(guild: discord.Guild, role_ids: list[int] | None) -> list[int]:
    """Conserve les IDs historiques puis complète avec le catalogue actuellement chargé."""
    result: list[int] = []
    for raw in role_ids or []:
        try:
            role_id = int(raw)
        except (TypeError, ValueError):
            continue
        if guild.get_role(role_id) is not None and role_id not in result:
            result.append(role_id)
    for role_id in _catalog_role_ids(guild):
        if role_id not in result:
            result.append(role_id)
    return result[:25]


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
        role_ids = _merge_role_ids(guild, role_ids)
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
        self.role_ids = role_ids
        self.mode = mode

    async def callback(self, interaction: discord.Interaction):
        # On accuse réception AVANT les appels Discord (ajout/retrait de rôle). Cela évite
        # définitivement « SentriX n'a pas répondu à temps » quand l'API Discord ralentit.
        if not interaction.response.is_done():
            await interaction.response.defer()

        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.edit_original_response(
                content="Ce panneau fonctionne uniquement dans un serveur.",
                view=None,
            )

        member = interaction.user
        guild = interaction.guild
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            return await interaction.edit_original_response(
                content="SentriX a besoin de la permission **Gérer les rôles**.",
                view=None,
            )

        selected_ids = [int(value) for value in self.values if value.isdigit() and value != "0"]
        roles: list[discord.Role] = []
        for role_id in selected_ids:
            role = guild.get_role(role_id)
            if role is None or role.managed or role >= bot_member.top_role:
                continue
            roles.append(role)

        if not roles:
            return await interaction.edit_original_response(
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
            return await interaction.edit_original_response(
                content="SentriX ne peut pas modifier ces rôles. Place son rôle au-dessus des rôles de notifications.",
                view=None,
            )
        except discord.HTTPException:
            return await interaction.edit_original_response(
                content="Discord a refusé la modification. Réessaie dans quelques secondes.",
                view=PersonalNotificationView(guild, member, self.role_ids, mode=self.mode),
            )

        fresh_member = member
        try:
            fresh_member = await guild.fetch_member(member.id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

        await interaction.edit_original_response(
            content=text,
            view=PersonalNotificationView(guild, fresh_member, self.role_ids, mode=self.mode),
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
    """Vue publique persistante.

    ``guild`` et ``role_ids`` sont optionnels afin de pouvoir enregistrer une vue globale.
    Cette vue globale sert de filet de sécurité aux anciens messages qui n'ont plus de ligne
    SQL ou dont la vue message-spécifique n'a pas été restaurée après un redémarrage.
    """

    def __init__(
        self,
        guild: discord.Guild | None = None,
        role_ids: list[int] | None = None,
    ):
        super().__init__(timeout=None)
        self.guild_id = guild.id if guild is not None else 0
        self.role_ids = list(role_ids or [])

    def _resolved_role_ids(self, guild: discord.Guild) -> list[int]:
        return _merge_role_ids(guild, self.role_ids)

    async def _open(self, interaction: discord.Interaction, mode: str) -> None:
        # Réponse immédiate : aucune DB, aucun fetch et aucune modification de rôle avant
        # l'ACK Discord. Même sous charge, le bouton ne peut plus expirer après 3 secondes.
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            if not interaction.response.is_done():
                return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        role_ids = self._resolved_role_ids(interaction.guild)
        if not role_ids:
            return await interaction.edit_original_response(
                content="Aucun rôle de notification n'est disponible sur ce serveur.",
                view=None,
            )

        if mode == "add":
            text = "Sélectionne les notifications que tu veux recevoir. Les rôles déjà pris ne sont pas affichés."
        else:
            text = "Sélectionne les notifications que tu veux retirer. Seuls tes rôles actuels sont affichés."

        await interaction.edit_original_response(
            content=text,
            view=PersonalNotificationView(
                interaction.guild,
                interaction.user,
                role_ids,
                mode=mode,
            ),
        )

    @discord.ui.button(
        label="Ajouter des notifications",
        style=discord.ButtonStyle.primary,
        custom_id="sentrix:notification-open:add",
    )
    async def add_notifications(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._open(interaction, "add")

    @discord.ui.button(
        label="Retirer des notifications",
        style=discord.ButtonStyle.secondary,
        custom_id="sentrix:notification-open:remove",
    )
    async def remove_notifications(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._open(interaction, "remove")


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
        return roles[:25]

    async def _save_panel(self, message: discord.Message, creator_id: int, role_ids: list[int]):
        await self.bot.db.execute(
            "INSERT INTO notification_role_panels "
            "(message_id, guild_id, channel_id, role_ids_json, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(message_id) DO UPDATE SET "
            "guild_id=excluded.guild_id, channel_id=excluded.channel_id, "
            "role_ids_json=excluded.role_ids_json, created_by=excluded.created_by",
            (
                message.id,
                message.guild.id,
                message.channel.id,
                json.dumps(role_ids[:25]),
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
            stored_ids = [int(value) for value in json.loads(row["role_ids_json"])]
        except Exception:
            stored_ids = []

        roles = await self._ensure_roles(ctx.guild)
        role_ids = _merge_role_ids(ctx.guild, [*stored_ids, *[role.id for role in roles]])

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


async def _restore_saved_views(bot: commands.Bot) -> None:
    try:
        rows = await bot.db.fetchall("SELECT * FROM notification_role_panels")
    except Exception:
        logger.exception("Lecture des panneaux de notifications impossible.")
        return

    for row in rows:
        guild = bot.get_guild(int(row["guild_id"]))
        if guild is None:
            continue
        try:
            stored_ids = [int(value) for value in json.loads(row["role_ids_json"])]
        except Exception:
            stored_ids = []
        role_ids = _merge_role_ids(guild, stored_ids)
        view = NotificationRoleView(guild, role_ids)

        # Message-specific : remplace dans le ViewStore une éventuelle ancienne vue cassée.
        bot.add_view(view, message_id=int(row["message_id"]))

        channel = guild.get_channel(int(row["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            continue
        try:
            message = await channel.fetch_message(int(row["message_id"]))
            await message.edit(embed=_panel_embed(guild, role_ids), view=view)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass


async def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # IMPORTANT : l'ancien code quittait ici si +rolepanel n'était pas encore chargé.
    # Le cog pouvait alors être forcé plus tard sans restaurer les vues persistantes, ce
    # qui produisait exactement « SentriX n'a pas répondu à temps » sur les boutons.
    await bot.db.execute(_SCHEMA)
    await bot.db.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_role_panels_guild "
        "ON notification_role_panels (guild_id, created_at)"
    )

    if bot.get_command("rolepanel") is not None:
        bot.remove_command("rolepanel")
    if bot.get_command("rolepanel-refresh") is not None:
        bot.remove_command("rolepanel-refresh")

    if bot.get_cog(_COG_NAME) is None:
        await bot.add_cog(NotificationRolePanels(bot))

    # Filet global : il répond aussi aux anciens panneaux dont la ligne SQL n'existe plus.
    if not getattr(bot, "_sentrix_notification_global_view_registered", False):
        bot.add_view(NotificationRoleView())
        bot._sentrix_notification_global_view_registered = True

    await _restore_saved_views(bot)

    _INSTALLED = True
    logger.info(
        "+rolepanel V2 actif : ACK immédiat + vue persistante globale + restauration des panneaux."
    )
