"""Navigation principale du panneau +setup / /setup SentriX V20."""
from __future__ import annotations

import discord
from discord.ext import commands

from utils import embeds, log_service
from utils.control_center_v20_meta import CHANNEL_COLUMNS, ROLE_COLUMNS, SETUP_CATEGORIES, _row_get
from utils.control_center_v20_access import _can_open_setup
from utils.control_center_v20_state import _category_embed, _home_embed, _setup_embed
from cogs.control_center_setup_components_v20 import (
    LogTypeSelectView, NumberModal, SanctionDmModal, SecurityToggleView,
    SetupResourcePicker, WelcomeTextModal,
)


class SetupCategorySelect(discord.ui.Select):
    def __init__(self, parent: "SetupControlView"):
        self.parent = parent
        super().__init__(
            placeholder="Choisir une catégorie",
            row=0,
            options=[
                discord.SelectOption(
                    label=meta["title"], value=key, description=meta["description"][:100]
                )
                for key, meta in SETUP_CATEGORIES.items()
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        if not await self.parent.interaction_check(interaction):
            return
        if self.parent.current is not None:
            self.parent.history.append(self.parent.current)
        self.parent.current = self.values[0]
        self.parent.rebuild()
        await interaction.response.edit_message(
            embed=await _category_embed(
                self.parent.bot, interaction.guild, self.parent.current
            ),
            view=self.parent,
        )


class SetupActionSelect(discord.ui.Select):
    ACTIONS = {
        "moderation": [
            ("moderation_staff_role", "Modifier le rôle staff"),
            ("moderation_warn_role", "Modifier le rôle d’avertissement"),
            ("warn_threshold", "Modifier le seuil de warns"),
            ("sanction_dm", "Modifier les MP de sanction"),
        ],
        "security": [
            ("security_toggle", "Activer / désactiver une protection"),
            ("security_commands", "Voir les commandes whitelist / exceptions"),
        ],
        "logs": [
            ("logs_channel", "Modifier le salon d’un log"),
            ("logs_toggle", "Activer / désactiver un log"),
            ("logs_create", "Créer les salons de logs manquants"),
        ],
        "tickets": [
            ("tickets_support_role", "Modifier le rôle support"),
            ("tickets_category", "Modifier la catégorie tickets"),
            ("tickets_ping", "Activer / désactiver le ping support"),
            ("tickets_transcript", "Activer / désactiver le transcript DM"),
            ("tickets_limit", "Modifier la limite par membre"),
            ("tickets_editor", "Ouvrir l’éditeur Tickets complet"),
        ],
        "welcome": [
            ("welcome_channel", "Modifier le salon de bienvenue"),
            ("goodbye_channel", "Modifier le salon de départ"),
            ("welcome_autorole", "Modifier l’autorole"),
            ("welcome_text", "Modifier messages et image"),
        ],
        "roles": [
            ("roles_autorole", "Modifier l’autorole"),
            ("roles_member", "Modifier le rôle membre"),
            ("roles_verify", "Modifier le rôle de vérification"),
            ("roles_booster", "Modifier le rôle booster"),
        ],
        "levels_economy": [
            ("levels_channel", "Modifier le salon level-up"),
            ("levels_shop", "Ouvrir les commandes boutique"),
            ("levels_retention", "Vérifier la conservation des données"),
        ],
        "notifications": [
            ("notifications_editor", "Ouvrir l’éditeur Notifications"),
            ("notifications_status", "Actualiser le diagnostic"),
        ],
        "ai": [
            ("ai_editor", "Ouvrir l’éditeur IA complet"),
            ("ai_toggle", "Activer / désactiver l’IA"),
        ],
    }

    def __init__(self, parent: "SetupControlView"):
        self.parent = parent
        actions = self.ACTIONS.get(parent.current or "", [])
        super().__init__(
            placeholder="Modifier cette catégorie",
            row=1,
            options=[
                discord.SelectOption(label=label, value=action)
                for action, label in actions
            ] or [discord.SelectOption(label="Aucune action", value="noop")],
        )

    async def callback(self, interaction: discord.Interaction):
        if not await self.parent.interaction_check(interaction):
            return
        await self.parent.handle_action(interaction, self.values[0])


class SetupControlView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int, author_id: int, channel_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.guild_id = int(guild_id)
        self.author_id = int(author_id)
        self.channel_id = int(channel_id)
        self.message_id: int | None = None
        self.current: str | None = None
        self.history: list[str | None] = []
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        self.add_item(SetupCategorySelect(self))
        if self.current:
            self.add_item(SetupActionSelect(self))
        home = discord.ui.Button(label="Accueil", style=discord.ButtonStyle.secondary, row=2)
        back = discord.ui.Button(
            label="Retour", style=discord.ButtonStyle.secondary, row=2,
            disabled=not self.history,
        )
        refresh = discord.ui.Button(
            label="Actualiser", style=discord.ButtonStyle.secondary, row=2
        )
        home.callback = self._home
        back.callback = self._back
        refresh.callback = self._refresh
        self.add_item(home)
        self.add_item(back)
        self.add_item(refresh)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        if await _can_open_setup(self.bot, interaction.guild, interaction.user):
            await interaction.response.send_message(
                embed=embeds.error(
                    "Ce panneau est déjà utilisé par un autre administrateur. "
                    "Ouvrez votre propre `+setup`."
                ),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                embed=embeds.error("Permission requise : **Administrateur**."),
                ephemeral=True,
            )
        return False

    async def _home(self, interaction: discord.Interaction):
        self.current = None
        self.history.clear()
        self.rebuild()
        await interaction.response.edit_message(
            embed=await _home_embed(self.bot, interaction.guild), view=self
        )

    async def _back(self, interaction: discord.Interaction):
        self.current = self.history.pop() if self.history else None
        self.rebuild()
        embed = await (
            _category_embed(self.bot, interaction.guild, self.current)
            if self.current else _home_embed(self.bot, interaction.guild)
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def _refresh(self, interaction: discord.Interaction):
        embed = await (
            _category_embed(self.bot, interaction.guild, self.current)
            if self.current else _home_embed(self.bot, interaction.guild)
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def refresh_main(self):
        if self.message_id is None:
            return
        guild = self.bot.get_guild(self.guild_id)
        channel = guild.get_channel(self.channel_id) if guild else None
        if channel is None or not hasattr(channel, "fetch_message"):
            return
        try:
            message = await channel.fetch_message(self.message_id)
            embed = await (
                _category_embed(self.bot, guild, self.current)
                if self.current else _home_embed(self.bot, guild)
            )
            self.rebuild()
            await message.edit(embed=embed, view=self)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

    async def log_change(self, user_id: int, module: str, action: str, old=None, new=None):
        logger = getattr(self.bot.db, "log_setup_history", None)
        if logger is None:
            return
        try:
            await logger(
                self.guild_id, int(user_id), module, action,
                old_value=None if old is None else str(old),
                new_value=None if new is None else str(new),
            )
        except Exception:
            return

    async def apply_resource(
        self, interaction: discord.Interaction, kind: str, action: str, value
    ):
        if action.startswith("log_channel:"):
            log_type = action.split(":", 1)[1]
            ok, reason = log_service.validate_channel(
                interaction.guild, value.id, needs_file=(log_type == "tickets")
            )
            if not ok:
                raise ValueError(reason)
            await log_service.set_log_channel(
                self.bot, self.guild_id, log_type, value.id
            )
            await log_service.set_log_enabled(
                self.bot, self.guild_id, log_type, True
            )
            await self.log_change(
                interaction.user.id, "Logs", f"salon {log_type}", new=value.id
            )
            return
        if action == "tickets_support_role":
            await self.bot.db.execute(
                "UPDATE ticket_types SET staff_role_id = ? WHERE guild_id = ?",
                (value.id, self.guild_id),
            )
            await self.log_change(
                interaction.user.id, "Tickets", "rôle support", new=value.id
            )
            return
        if action == "tickets_category":
            await self.bot.db.execute(
                "UPDATE ticket_types SET category_id = ? WHERE guild_id = ?",
                (value.id, self.guild_id),
            )
            await self.bot.db.set_guild_config(
                self.guild_id, "ticket_category", value.id
            )
            await self.log_change(
                interaction.user.id, "Tickets", "catégorie", new=value.id
            )
            return
        mapping = ROLE_COLUMNS if kind == "role" else CHANNEL_COLUMNS
        column, label = mapping[action]
        old_conf = await self.bot.db.get_guild_config(self.guild_id)
        old = _row_get(old_conf, column)
        await self.bot.db.set_guild_config(self.guild_id, column, value.id)
        await self.log_change(
            interaction.user.id, self.current or "Configuration", label,
            old=old, new=value.id,
        )

    async def apply_number(
        self, interaction: discord.Interaction, action: str, value: int
    ):
        if action == "warn_threshold":
            if not 0 <= value <= 100:
                raise ValueError("Le seuil doit être compris entre 0 et 100.")
            await self.bot.db.set_guild_config(
                self.guild_id, "warn_ban_threshold", value
            )
            await self.log_change(
                interaction.user.id, "Modération", "seuil warns", new=value
            )
        elif action == "tickets_limit":
            if not 1 <= value <= 20:
                raise ValueError(
                    "La limite doit être comprise entre 1 et 20 tickets par membre."
                )
            await self.bot.db.execute(
                "UPDATE ticket_panels_v2 SET max_per_member = ? WHERE guild_id = ?",
                (value, self.guild_id),
            )
            await self.bot.db.execute(
                "UPDATE ticket_types SET max_per_member = ? WHERE guild_id = ?",
                (value, self.guild_id),
            )
            await self.log_change(
                interaction.user.id, "Tickets", "limite par membre", new=value
            )

    async def handle_action(self, interaction: discord.Interaction, action: str):
        if action in ROLE_COLUMNS:
            _column, label = ROLE_COLUMNS[action]
            return await interaction.response.send_message(
                embed=embeds.neutral(
                    "Sélection de rôle", f"Choisissez le nouveau **{label}**."
                ),
                view=SetupResourcePicker(
                    self, kind="role", action=action, label=label
                ),
                ephemeral=True,
            )
        if action in CHANNEL_COLUMNS:
            _column, label = CHANNEL_COLUMNS[action]
            return await interaction.response.send_message(
                embed=embeds.neutral(
                    "Sélection de salon", f"Choisissez le nouveau **{label}**."
                ),
                view=SetupResourcePicker(
                    self, kind="channel", action=action, label=label
                ),
                ephemeral=True,
            )
        if action == "warn_threshold":
            conf = await self.bot.db.get_guild_config(self.guild_id)
            return await interaction.response.send_modal(
                NumberModal(
                    self, action, "Seuil de warns",
                    "Nombre de warns avant ban (0 = désactivé)",
                    str(_row_get(conf, "warn_ban_threshold", 3)),
                )
            )
        if action == "sanction_dm":
            return await interaction.response.send_modal(SanctionDmModal(self))
        if action == "security_toggle":
            return await interaction.response.send_message(
                embed=embeds.neutral(
                    "Sécurité", "Choisissez la protection à modifier."
                ),
                view=SecurityToggleView(self), ephemeral=True,
            )
        if action == "security_commands":
            return await interaction.response.send_message(
                embed=embeds.neutral(
                    "Exceptions et whitelist",
                    "Utilisez `+help whitelist-domain`, `+help automod-exempt-role-add` "
                    "ou `+help blacklist-add` pour les réglages avancés."
                ),
                ephemeral=True,
            )
        if action == "logs_channel":
            return await interaction.response.send_message(
                embed=embeds.neutral(
                    "Logs", "Choisissez le type de log, puis son salon."
                ),
                view=LogTypeSelectView(self, "channel"), ephemeral=True,
            )
        if action == "logs_toggle":
            return await interaction.response.send_message(
                embed=embeds.neutral(
                    "Logs", "Choisissez le type de log à activer ou désactiver."
                ),
                view=LogTypeSelectView(self, "toggle"), ephemeral=True,
            )
        if action == "logs_create":
            configuration = self.bot.get_cog("Configuration")
            creator = getattr(configuration, "create_log_channels", None)
            if creator is None:
                return await interaction.response.send_message(
                    embed=embeds.error(
                        "Le service de création des logs n’est pas disponible."
                    ),
                    ephemeral=True,
                )
            if not interaction.guild.me.guild_permissions.manage_channels:
                return await interaction.response.send_message(
                    embed=embeds.error(
                        "Permission SentriX manquante : **Gérer les salons**."
                    ),
                    ephemeral=True,
                )
            await interaction.response.defer(ephemeral=True, thinking=True)
            created = await creator(interaction.guild, interaction.user)
            await interaction.followup.send(
                embed=embeds.success(f"{len(created)} salon(s) de logs créé(s)."),
                ephemeral=True,
            )
            await self.refresh_main()
            return
        if action == "tickets_support_role":
            return await interaction.response.send_message(
                embed=embeds.neutral(
                    "Tickets",
                    "Choisissez le rôle support. Il sera appliqué aux types de tickets existants."
                ),
                view=SetupResourcePicker(
                    self, kind="role", action=action, label="Rôle support"
                ),
                ephemeral=True,
            )
        if action == "tickets_category":
            return await interaction.response.send_message(
                embed=embeds.neutral(
                    "Tickets",
                    "Choisissez la catégorie utilisée par les types de tickets existants."
                ),
                view=SetupResourcePicker(
                    self, kind="channel", action=action, label="Catégorie tickets"
                ),
                ephemeral=True,
            )
        if action == "tickets_ping":
            row = await self.bot.db.fetchone(
                "SELECT mention_staff FROM ticket_types WHERE guild_id = ? LIMIT 1",
                (self.guild_id,),
            )
            if row is None:
                return await interaction.response.send_message(
                    embed=embeds.error(
                        "Créez d’abord au moins un type de ticket dans l’éditeur Tickets."
                    ),
                    ephemeral=True,
                )
            enabled = bool(_row_get(row, "mention_staff", 1))
            await self.bot.db.execute(
                "UPDATE ticket_types SET mention_staff = ? WHERE guild_id = ?",
                (0 if enabled else 1, self.guild_id),
            )
            await self.log_change(
                interaction.user.id, "Tickets", "ping support", new=not enabled
            )
            await interaction.response.edit_message(
                embed=await _category_embed(self.bot, interaction.guild, "tickets"),
                view=self,
            )
            return
        if action == "tickets_transcript":
            conf = await self.bot.db.get_guild_config(self.guild_id)
            enabled = bool(_row_get(conf, "ticket_transcript_dm", 1))
            await self.bot.db.set_guild_config(
                self.guild_id, "ticket_transcript_dm", 0 if enabled else 1
            )
            await self.log_change(
                interaction.user.id, "Tickets", "transcript DM", new=not enabled
            )
            await interaction.response.edit_message(
                embed=await _category_embed(self.bot, interaction.guild, "tickets"),
                view=self,
            )
            return
        if action == "tickets_limit":
            return await interaction.response.send_modal(
                NumberModal(
                    self, action, "Limite de tickets",
                    "Tickets simultanés par membre (1-20)", "1",
                )
            )
        if action == "tickets_editor":
            tickets = self.bot.get_cog("Tickets")
            if tickets is None:
                return await interaction.response.send_message(
                    embed=embeds.error("Le module Tickets n’est pas chargé."),
                    ephemeral=True,
                )
            try:
                from cogs.tickets import TicketSetupHubView
                panels = await self.bot.db.fetchall(
                    "SELECT * FROM ticket_panels_v2 WHERE guild_id = ?",
                    (self.guild_id,),
                )
                types = await self.bot.db.fetchall(
                    "SELECT * FROM ticket_types WHERE guild_id = ?",
                    (self.guild_id,),
                )
                opened = await self.bot.db.fetchone(
                    "SELECT COUNT(*) AS c FROM tickets WHERE guild_id = ? AND status = 'ouvert'",
                    (self.guild_id,),
                )
                panel = _setup_embed(
                    "SentriX — Tickets — Réglages avancés",
                    "Éditeur complet des panels, types, formulaires et boutons staff. "
                    "Les modifications utilisent la même base que +setup.",
                )
                panel.add_field(name="Panels", value=str(len(panels)), inline=True)
                panel.add_field(name="Types", value=str(len(types)), inline=True)
                panel.add_field(
                    name="Tickets ouverts",
                    value=str(int(_row_get(opened, "c", 0))),
                    inline=True,
                )
                return await interaction.response.send_message(
                    embed=panel,
                    view=TicketSetupHubView(tickets, interaction.user.id),
                    ephemeral=True,
                )
            except (ImportError, AttributeError):
                return await interaction.response.send_message(
                    embed=embeds.neutral(
                        "SentriX — Tickets — Réglages avancés",
                        "L’éditeur avancé reste disponible avec `+ticketsetup`. "
                        "Les données ne sont pas dupliquées."
                    ),
                    ephemeral=True,
                )
        if action == "welcome_text":
            conf = await self.bot.db.get_guild_config(self.guild_id)
            return await interaction.response.send_modal(WelcomeTextModal(self, conf))
        if action == "levels_shop":
            return await interaction.response.send_message(
                embed=embeds.neutral(
                    "Niveaux et économie",
                    "Boutique : `+shopsetup`. Récompenses de niveau : "
                    "`+help set-level-role`. Le setup principal conserve et diagnostique "
                    "les valeurs existantes."
                ),
                ephemeral=True,
            )
        if action == "levels_retention":
            return await interaction.response.send_message(
                embed=embeds.neutral(
                    "Conservation des données",
                    "Le départ, kick, ban ou bannissement par un autre bot ne supprime pas "
                    "automatiquement le niveau, l’XP, le nombre de messages, l’argent, "
                    "la banque ni les statistiques. Les resets restent des actions explicites."
                ),
                ephemeral=True,
            )
        if action == "notifications_editor":
            return await interaction.response.send_message(
                embed=embeds.neutral(
                    "Notifications",
                    "Ajoutez ou modifiez une source avec `+notifs-ping`. Le diagnostic de "
                    "cette page vérifie ensuite le salon, le rôle et l’état YouTube/Twitch/TikTok."
                ),
                ephemeral=True,
            )
        if action == "notifications_status":
            return await interaction.response.edit_message(
                embed=await _category_embed(
                    self.bot, interaction.guild, "notifications"
                ),
                view=self,
            )
        if action == "ai_toggle":
            from utils import ai_service
            settings = await ai_service.get_settings(self.bot, self.guild_id)
            await ai_service.update_setting(
                self.bot, self.guild_id, "enabled", int(not settings["enabled"])
            )
            await self.log_change(
                interaction.user.id, "IA", "activation", new=not settings["enabled"]
            )
            return await interaction.response.edit_message(
                embed=await _category_embed(self.bot, interaction.guild, "ai"),
                view=self,
            )
        if action == "ai_editor":
            from cogs.ai import AiSetupView
            from utils import ai_service
            cog = self.bot.get_cog("Ai")
            if cog is None:
                return await interaction.response.send_message(
                    embed=embeds.error("Le module IA n’est pas chargé."), ephemeral=True
                )
            settings = await ai_service.get_settings(self.bot, self.guild_id)
            view = AiSetupView(cog, self.guild_id, interaction.user.id, settings)
            return await interaction.response.send_message(
                embed=view.build_embed(), view=view, ephemeral=True
            )
        await interaction.response.send_message(
            embed=embeds.error("Action indisponible."), ephemeral=True
        )
