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

from utils import embeds
from utils import sentrix_panels as panels
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
            'Choisissez uniquement les notifications que vous voulez recevoir.\n\nCliquez sur **Ajouter des notifications** pour prendre des rôles ou sur **Retirer des notifications** pour enlever ceux que vous ne veux plus.'
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
        value='Vos choix sont privés et le panneau reste identique pour les autres membres.',
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



def _reponse(titre: str, description: str = "", *, kind: str = "configuration"):
    """Reponse composee : banniere, titre, et le detail en section quand il y en a.

    Une description sur plusieurs lignes devient une SECTION plutot qu'un
    paragraphe : ces reponses enumerent souvent des reglages ou des etats, et une
    enumeration se lit mal d'un bloc.
    """
    # Pas de section ici : une confirmation d'une ligne n'a rien a structurer, et
    # fabriquer une section « Détail » autour d'une phrase ne ferait que deplacer
    # du texte. Ce niveau est l'IDENTITE — banniere, accent, titre. Les ecrans qui
    # ont vraiment de la matiere sont composes a la main, la ou ils sont ecrits.
    resume = " ".join(l.strip() for l in str(description or "").split("\n") if l.strip())
    return panels.Panneau(
        titre=titre if titre.startswith("SentriX") else f"SentriX — {titre}",
        sous_titre=resume,
        kind=kind if kind in panels.INTENTIONS else "configuration",
        pied="SentriX",
    )


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
                        'Vous avez déjà tous les rôles.' if mode == "add"
                        else "Vous n'avez aucun rôle de notification."
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
        # ACK avant toute action réseau : Discord ne peut plus afficher « n'a pas répondu ».
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
                content='SentriX ne peut pas modifier ces rôles. Placez son rôle au-dessus des rôles de notifications.',
                view=None,
            )
        except discord.HTTPException:
            return await interaction.edit_original_response(
                content='Discord a refusé la modification. Réessayez dans quelques secondes.',
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
    """Vue publique persistante avec fallback global pour les anciens messages."""

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
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            if not interaction.response.is_done():
                await panels.envoyer(interaction, _reponse('Panneau de rôles', 'Serveur introuvable.', kind='danger'), ephemere=True)
            return

        # ACK immédiat. Le menu est construit seulement après l'accusé de réception Discord.
        await interaction.response.defer(ephemeral=True, thinking=True)
        role_ids = self._resolved_role_ids(interaction.guild)
        if not role_ids:
            return await interaction.edit_original_response(
                content="Aucun rôle de notification n'est disponible sur ce serveur.",
                view=None,
            )

        text = (
            "Sélectionne les notifications que tu veux recevoir. Les rôles déjà pris ne sont pas affichés."
            if mode == "add"
            else "Sélectionne les notifications que tu veux retirer. Seuls tes rôles actuels sont affichés."
        )
        await interaction.edit_original_response(
            content=text,
            view=PersonalNotificationView(interaction.guild, interaction.user, role_ids, mode=mode),
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
            return await panels.envoyer(ctx, _reponse('Panneau de rôles', 'SentriX a besoin de la permission **Gérer les rôles** pour créer le panneau.', kind='danger'))
        except discord.Forbidden:
            return await panels.envoyer(ctx, _reponse('Panneau de rôles', 'Je ne peux pas créer les rôles. Vérifiez la permission **Gérer les rôles**.', kind='danger'))

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
            return await panels.envoyer(ctx, _reponse('Panneau de rôles', "Aucun panneau de notifications SentriX n'a été trouvé sur ce serveur.", kind='warning'))

        try:
            stored_ids = [int(value) for value in json.loads(row["role_ids_json"])]
        except Exception:
            stored_ids = []

        roles = await self._ensure_roles(ctx.guild)
        role_ids = _merge_role_ids(ctx.guild, [*stored_ids, *[role.id for role in roles]])

        channel = ctx.guild.get_channel(int(row["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return await panels.envoyer(ctx, _reponse('Panneau de rôles', "Le salon du panneau n'existe plus.", kind='danger'))
        try:
            message = await channel.fetch_message(int(row["message_id"]))
        except discord.NotFound:
            return await panels.envoyer(ctx, _reponse('Panneau de rôles', 'Le message du panneau a été supprimé. Relancez `+rolepanel`.', kind='success'))
        except discord.Forbidden:
            return await panels.envoyer(ctx, _reponse('Panneau de rôles', 'SentriX ne peut pas accéder au message du panneau.', kind='danger'))

        view = NotificationRoleView(ctx.guild, role_ids)
        await message.edit(embed=_panel_embed(ctx.guild, role_ids), view=view)
        await self._save_panel(message, ctx.author.id, role_ids)
        self.bot.add_view(NotificationRoleView(ctx.guild, role_ids), message_id=message.id)
        await panels.envoyer(ctx, _reponse('Panneau de rôles', 'Le panneau de notifications a été mis à jour.', kind='success'))


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

        # Remplace dans le ViewStore une éventuelle ancienne vue message-spécifique cassée.
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

    await bot.db.execute(_SCHEMA)
    await bot.db.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_role_panels_guild "
        "ON notification_role_panels (guild_id, created_at)"
    )

    # Toujours disponible, même avant le chargement de l'ancienne commande +rolepanel.
    # Cette vue globale suffit déjà à rendre les anciens boutons cliquables après restart.
    if not getattr(bot, "_sentrix_notification_global_view_registered", False):
        bot.add_view(NotificationRoleView())
        bot._sentrix_notification_global_view_registered = True

    # Au READY, le cache des guilds est complet : on réattache une vue précise à chaque
    # message sauvegardé et on remplace les handlers devenus obsolètes.
    if not getattr(bot, "_sentrix_notification_restore_listener", False):
        async def restore_on_ready() -> None:
            try:
                await _restore_saved_views(bot)
            except Exception:
                logger.exception("Restauration READY des panneaux de notifications impossible.")

        bot.add_listener(restore_on_ready, "on_ready")
        bot._sentrix_notification_restore_listener = True

    # L'ancien +rolepanel est défini dans une extension chargée plus tard. On ne doit pas
    # ajouter notre Cog avant cette extension, sinon discord.py refuse son chargement pour
    # doublon de commande. On garde donc les vues actives et on réessaie au prochain cog.
    old = bot.get_command("rolepanel")
    if old is None:
        return

    bot.remove_command("rolepanel")
    if bot.get_command("rolepanel-refresh") is not None:
        bot.remove_command("rolepanel-refresh")

    if bot.get_cog(_COG_NAME) is None:
        await bot.add_cog(NotificationRolePanels(bot))

    if bot.is_ready():
        await _restore_saved_views(bot)

    _INSTALLED = True
    logger.info(
        "+rolepanel V2 actif : ACK immédiat + fallback persistant + restauration READY."
    )
