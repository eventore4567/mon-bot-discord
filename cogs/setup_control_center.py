"""Centre de configuration officiel de SentriX.

Le nouveau +setup et /setup utilisent le même contrôleur, modifient toujours le même
message et lisent les configurations historiques au lieu de les recréer.
"""
from __future__ import annotations

from enum import Enum

import discord
from discord import app_commands
from discord.ext import commands

from utils import checks, embeds, log_service


class ConfigState(str, Enum):
    ACTIVE = "ACTIF"
    INACTIVE = "INACTIF"
    UNCONFIGURED = "NON CONFIGURÉ"
    ERROR = "ERREUR DE CONFIGURATION"


CATEGORIES = {
    "moderation": ("Modération", "Sanctions, rôles staff et permissions de modération."),
    "security": ("Sécurité", "Anti-spam, anti-raid, liens, mentions et protection du serveur."),
    "logs": ("Logs", "Messages, membres, rôles, salons, vocal, tickets et sécurité."),
    "tickets": ("Tickets", "Panels, types, catégories, rôles support et options des tickets."),
    "welcome": ("Bienvenue & départ", "Accueil, départ, messages, image et rôle automatique."),
    "roles": ("Rôles", "Autorôles, vérification, rôles membres et récompenses."),
    "levels": ("Niveaux & économie", "XP, activité, argent, banque, récompenses et boutique."),
    "notifications": ("Notifications", "YouTube, Twitch et TikTok, salons et rôles mentionnés."),
    "ai": ("IA", "Assistant SentriX, limites, permissions et génération d’images."),
}
CATEGORY_ORDER = tuple(CATEGORIES)

AUTOMOD = (
    ("antispam", "Anti-spam"), ("antiraid", "Anti-raid"), ("antilink", "Anti-lien"),
    ("antiinvite", "Anti-invitation"), ("antimention", "Anti-ping"), ("anticaps", "Anti-majuscules"),
    ("antiemoji", "Anti-emoji"), ("antibot", "Anti-bot"), ("antiaccount", "Anti-compte récent"),
    ("antiscam", "Anti-scam"), ("antinuke", "Anti-nuke"),
)

BOT_PERMS = {
    "moderation": ("manage_messages", "moderate_members", "kick_members", "ban_members"),
    "security": ("manage_messages", "manage_roles", "manage_channels", "view_audit_log"),
    "logs": ("view_channel", "send_messages", "embed_links", "view_audit_log"),
    "tickets": ("manage_channels", "manage_roles", "view_channel", "send_messages"),
    "welcome": ("view_channel", "send_messages", "embed_links", "manage_roles"),
    "roles": ("manage_roles",),
    "levels": ("view_channel", "send_messages", "embed_links"),
    "notifications": ("view_channel", "send_messages", "embed_links", "mention_everyone"),
    "ai": ("view_channel", "send_messages", "embed_links", "attach_files"),
}
PERM_LABELS = {
    "view_channel": "Voir les salons", "send_messages": "Envoyer des messages",
    "embed_links": "Intégrer des liens", "attach_files": "Joindre des fichiers",
    "manage_messages": "Gérer les messages", "moderate_members": "Modérer les membres",
    "kick_members": "Expulser des membres", "ban_members": "Bannir des membres",
    "manage_roles": "Gérer les rôles", "manage_channels": "Gérer les salons",
    "view_audit_log": "Voir les logs d’audit",
    "mention_everyone": "Mentionner @everyone/@here et les rôles",
}


def _get(row, key, default=None):
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _role(guild, role_id):
    if not role_id:
        return "Non configuré"
    obj = guild.get_role(int(role_id))
    return obj.mention if obj else f"Introuvable (`{role_id}`)"


def _channel(guild, channel_id):
    if not channel_id:
        return "Non configuré"
    obj = guild.get_channel(int(channel_id))
    return obj.mention if obj else f"Introuvable (`{channel_id}`)"


def _missing_resource(guild, resource_id, role=False):
    if not resource_id:
        return False
    return (guild.get_role(int(resource_id)) if role else guild.get_channel(int(resource_id))) is None


def _completion(statuses):
    complete = sum(state in {ConfigState.ACTIVE, ConfigState.INACTIVE} for state, _, _ in statuses.values())
    return round(complete / len(statuses) * 100) if statuses else 0


async def _can_setup(bot, member, guild):
    if guild is None or not isinstance(member, discord.Member):
        return False

    class Ctx:
        pass

    ctx = Ctx()
    ctx.author, ctx.bot, ctx.guild = member, bot, guild
    return bool(await checks.is_verified_bot_owner(ctx) or member.guild_permissions.administrator)


async def _permission_error(target):
    panel = embeds.error(
        "Vous ne pouvez pas ouvrir la configuration de ce serveur.\n\n"
        "**Permission requise :** Administrateur"
    )
    if isinstance(target, commands.Context):
        return await target.send(embed=panel)
    if target.response.is_done():
        return await target.followup.send(embed=panel, ephemeral=True)
    return await target.response.send_message(embed=panel, ephemeral=True)


async def module_statuses(bot, guild, conf):
    result = {}

    roles = [("mod_role", "Rôle staff"), ("mute_role", "Rôle mute"), ("warn_role", "Rôle warn")]
    bad = [label for field, label in roles if _missing_resource(guild, _get(conf, field), role=True)]
    configured = any(_get(conf, field) for field, _ in roles)
    result["moderation"] = (
        ConfigState.ERROR if bad else ConfigState.ACTIVE if configured else ConfigState.UNCONFIGURED,
        "Rôles staff et sanctions.",
        tuple(f"{label} introuvable." for label in bad),
    )

    automod = await bot.db.fetchone("SELECT * FROM automod_settings WHERE guild_id = ?", (guild.id,))
    active_security = sum(bool(_get(automod, field, 0)) for field, _ in AUTOMOD) if automod else 0
    result["security"] = (
        ConfigState.ACTIVE if active_security else ConfigState.INACTIVE if automod else ConfigState.UNCONFIGURED,
        f"{active_security}/{len(AUTOMOD)} protections actives.",
        (),
    )

    active_logs = configured_logs = 0
    log_errors = []
    for log_type, meta in log_service.LOG_TYPES.items():
        if not meta.get("emits"):
            continue
        setting = await log_service.get_log_setting(bot, guild.id, log_type)
        channel_id = setting.get("channel_id")
        if channel_id:
            configured_logs += 1
        if setting.get("enabled"):
            active_logs += 1
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            if channel is None:
                log_errors.append(f"{meta['category']} : salon introuvable.")
            else:
                perms = channel.permissions_for(guild.me)
                if not (perms.view_channel and perms.send_messages):
                    log_errors.append(f"{meta['category']} : permissions du salon insuffisantes.")
    result["logs"] = (
        ConfigState.ERROR if log_errors else ConfigState.ACTIVE if active_logs else ConfigState.INACTIVE if configured_logs else ConfigState.UNCONFIGURED,
        f"{active_logs} type(s) actif(s).",
        tuple(log_errors),
    )

    panels = await bot.db.fetchall("SELECT id, channel_id, enabled FROM ticket_panels_v2 WHERE guild_id = ?", (guild.id,))
    types = await bot.db.fetchall(
        "SELECT id, staff_role_id, category_id, log_channel_id FROM ticket_types WHERE guild_id = ?", (guild.id,)
    )
    ticket_errors = []
    for row in panels:
        if _missing_resource(guild, _get(row, "channel_id")):
            ticket_errors.append("Un salon de panel n’existe plus.")
    for row in types:
        if _missing_resource(guild, _get(row, "staff_role_id"), role=True):
            ticket_errors.append("Un rôle support n’existe plus.")
        if _missing_resource(guild, _get(row, "category_id")):
            ticket_errors.append("Une catégorie de tickets n’existe plus.")
        if _missing_resource(guild, _get(row, "log_channel_id")):
            ticket_errors.append("Un salon de logs tickets n’existe plus.")
    has_tickets = bool(panels or types or _get(conf, "ticket_category") or _get(conf, "ticket_log_channel"))
    enabled_panels = any(bool(_get(row, "enabled", 1)) for row in panels)
    result["tickets"] = (
        ConfigState.ERROR if ticket_errors else ConfigState.ACTIVE if (types or enabled_panels) else ConfigState.INACTIVE if has_tickets else ConfigState.UNCONFIGURED,
        f"{len(panels)} panel(s) • {len(types)} type(s).",
        tuple(ticket_errors),
    )

    welcome_values = [
        (_get(conf, "welcome_channel"), False, "Salon de bienvenue"),
        (_get(conf, "goodbye_channel"), False, "Salon de départ"),
        (_get(conf, "autorole"), True, "Autorole"),
    ]
    welcome_errors = [f"{label} introuvable." for value, role, label in welcome_values if _missing_resource(guild, value, role)]
    result["welcome"] = (
        ConfigState.ERROR if welcome_errors else ConfigState.ACTIVE if any(v for v, _, _ in welcome_values) else ConfigState.UNCONFIGURED,
        "Accueil, départ et autorole.",
        tuple(welcome_errors),
    )

    role_values = [(_get(conf, key), key) for key in ("autorole", "verify_role", "verification_role", "member_role", "booster_role")]
    level_roles = await bot.db.fetchall("SELECT level, role_id FROM level_roles WHERE guild_id = ?", (guild.id,))
    role_errors = [f"Rôle `{key}` introuvable." for value, key in role_values if _missing_resource(guild, value, True)]
    role_errors += [
        f"Récompense niveau {_get(row, 'level')} introuvable."
        for row in level_roles if _missing_resource(guild, _get(row, "role_id"), True)
    ]
    result["roles"] = (
        ConfigState.ERROR if role_errors else ConfigState.ACTIVE if any(v for v, _ in role_values) or level_roles else ConfigState.UNCONFIGURED,
        f"{len(level_roles)} récompense(s) de niveau.",
        tuple(role_errors),
    )

    level_count = await bot.db.fetchone("SELECT COUNT(*) AS n FROM levels WHERE guild_id = ?", (guild.id,))
    economy_count = await bot.db.fetchone("SELECT COUNT(*) AS n FROM economy WHERE guild_id = ?", (guild.id,))
    shop_count = await bot.db.fetchone("SELECT COUNT(*) AS n FROM shop_items WHERE guild_id = ?", (guild.id,))
    level_error = _missing_resource(guild, _get(conf, "level_channel"))
    used = _get(level_count, "n", 0) or _get(economy_count, "n", 0) or _get(shop_count, "n", 0) or _get(conf, "level_channel")
    result["levels"] = (
        ConfigState.ERROR if level_error else ConfigState.ACTIVE if used else ConfigState.UNCONFIGURED,
        f"{_get(level_count, 'n', 0)} niveau(x) • {_get(economy_count, 'n', 0)} compte(s) • {_get(shop_count, 'n', 0)} article(s).",
        ("Le salon de level-up n’existe plus.",) if level_error else (),
    )

    notifications = await bot.db.fetchall(
        "SELECT platform, discord_channel_id, role_id, enabled FROM social_notifications WHERE guild_id = ?", (guild.id,)
    )
    notif_errors, active_notifs = [], 0
    for row in notifications:
        if _get(row, "enabled", 1):
            active_notifs += 1
            if _missing_resource(guild, _get(row, "discord_channel_id")):
                notif_errors.append(f"{_get(row, 'platform', 'Notification')} : salon introuvable.")
            if _missing_resource(guild, _get(row, "role_id"), True):
                notif_errors.append(f"{_get(row, 'platform', 'Notification')} : rôle introuvable.")
    result["notifications"] = (
        ConfigState.ERROR if notif_errors else ConfigState.ACTIVE if active_notifs else ConfigState.INACTIVE if notifications else ConfigState.UNCONFIGURED,
        f"{active_notifs}/{len(notifications)} source(s) active(s).",
        tuple(notif_errors),
    )

    ai = await bot.db.fetchone("SELECT * FROM ai_settings WHERE guild_id = ?", (guild.id,))
    result["ai"] = (
        ConfigState.ACTIVE if _get(ai, "enabled", 1) else ConfigState.INACTIVE,
        "Valeurs par défaut SentriX." if ai is None else f"Cooldown {_get(ai, 'cooldown_seconds', 8)} s • {_get(ai, 'daily_limit', 50)}/jour.",
        (),
    )
    return result


class CategorySelect(discord.ui.Select):
    def __init__(self, view):
        self.owner = view
        super().__init__(
            placeholder="Choisir une catégorie",
            options=[discord.SelectOption(label=CATEGORIES[key][0], value=key, description=CATEGORIES[key][1][:100]) for key in CATEGORY_ORDER],
            row=0,
        )

    async def callback(self, interaction):
        self.owner.category = self.values[0]
        self.owner.selected_log = self.owner.selected_ticket = self.owner.selected_notification = None
        await self.owner.refresh(interaction)


class FieldRoleSelect(discord.ui.RoleSelect):
    def __init__(self, view, field, label, row):
        self.owner, self.field = view, field
        super().__init__(placeholder=label, min_values=0, max_values=1, row=row)

    async def callback(self, interaction):
        value = self.values[0].id if self.values else None
        await self.owner.bot.db.set_guild_config(self.owner.guild.id, self.field, value)
        await self.owner.audit(interaction.user.id, self.field, value)
        await self.owner.refresh(interaction)


class FieldChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, view, field, label, row):
        self.owner, self.field = view, field
        super().__init__(
            placeholder=label, min_values=0, max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news], row=row,
        )

    async def callback(self, interaction):
        value = self.values[0].id if self.values else None
        await self.owner.bot.db.set_guild_config(self.owner.guild.id, self.field, value)
        await self.owner.audit(interaction.user.id, self.field, value)
        await self.owner.refresh(interaction)


class AutomodSelect(discord.ui.Select):
    def __init__(self, view):
        self.owner = view
        super().__init__(
            placeholder="Protections actives", min_values=0, max_values=len(AUTOMOD),
            options=[discord.SelectOption(label=label, value=field) for field, label in AUTOMOD], row=2,
        )

    async def callback(self, interaction):
        chosen = set(self.values)
        await self.owner.bot.db.execute(
            "INSERT INTO automod_settings (guild_id) VALUES (?) ON CONFLICT(guild_id) DO NOTHING",
            (self.owner.guild.id,),
        )
        columns = ", ".join(f"{field} = ?" for field, _ in AUTOMOD)
        values = tuple(1 if field in chosen else 0 for field, _ in AUTOMOD)
        await self.owner.bot.db.execute(
            f"UPDATE automod_settings SET {columns} WHERE guild_id = ?",
            (*values, self.owner.guild.id),
        )
        await self.owner.audit(interaction.user.id, "protections", ",".join(sorted(chosen)))
        await self.owner.refresh(interaction)


class LogSelect(discord.ui.Select):
    def __init__(self, view):
        self.owner = view
        options = [
            discord.SelectOption(label=meta["label"][:100], value=key)
            for key, meta in log_service.LOG_TYPES.items() if meta.get("emits")
        ]
        super().__init__(placeholder="Choisir un type de log", options=options, row=2)

    async def callback(self, interaction):
        self.owner.selected_log = self.values[0]
        await self.owner.refresh(interaction)


class LogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, view):
        self.owner = view
        super().__init__(
            placeholder="Salon de ce log", min_values=0, max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news], row=3,
        )

    async def callback(self, interaction):
        setting = await log_service.get_log_setting(self.owner.bot, self.owner.guild.id, self.owner.selected_log)
        channel_id = self.values[0].id if self.values else None
        await self.owner.bot.db.execute(
            "UPDATE log_settings SET channel_id = ?, enabled = ?, updated_at = strftime('%s','now') "
            "WHERE guild_id = ? AND log_type = ?",
            (channel_id, int(bool(setting.get("enabled")) and channel_id is not None), self.owner.guild.id, self.owner.selected_log),
        )
        await self.owner.audit(interaction.user.id, self.owner.selected_log, channel_id)
        await self.owner.refresh(interaction)


class TicketSelect(discord.ui.Select):
    def __init__(self, view, rows):
        self.owner = view
        options = [
            discord.SelectOption(label=str(_get(row, "name", "Ticket"))[:100], value=str(_get(row, "id")))
            for row in rows[:25]
        ] or [discord.SelectOption(label="Aucun type de ticket", value="none")]
        super().__init__(placeholder="Choisir un type de ticket", options=options, row=2)

    async def callback(self, interaction):
        if self.values[0] != "none":
            self.owner.selected_ticket = int(self.values[0])
        await self.owner.refresh(interaction)


class TicketCategorySelect(discord.ui.ChannelSelect):
    def __init__(self, view):
        self.owner = view
        super().__init__(
            placeholder="Catégorie du type de ticket", min_values=0, max_values=1,
            channel_types=[discord.ChannelType.category], row=3,
        )

    async def callback(self, interaction):
        value = self.values[0].id if self.values else None
        await self.owner.bot.db.execute(
            "UPDATE ticket_types SET category_id = ? WHERE guild_id = ? AND id = ?",
            (value, self.owner.guild.id, self.owner.selected_ticket),
        )
        await self.owner.audit(interaction.user.id, "ticket_category", value)
        await self.owner.refresh(interaction)


class TicketRoleSelect(discord.ui.RoleSelect):
    def __init__(self, view):
        self.owner = view
        super().__init__(placeholder="Rôle support de ce type", min_values=0, max_values=1, row=4)

    async def callback(self, interaction):
        value = self.values[0].id if self.values else None
        await self.owner.bot.db.execute(
            "UPDATE ticket_types SET staff_role_id = ? WHERE guild_id = ? AND id = ?",
            (value, self.owner.guild.id, self.owner.selected_ticket),
        )
        await self.owner.audit(interaction.user.id, "ticket_support", value)
        await self.owner.refresh(interaction)


class NotificationSelect(discord.ui.Select):
    def __init__(self, view, rows):
        self.owner = view
        options = [
            discord.SelectOption(
                label=f"{str(_get(row, 'platform', 'notification')).title()} #{_get(row, 'id')}"[:100],
                value=str(_get(row, "id")), description=str(_get(row, "source_url", ""))[:100],
            ) for row in rows[:25]
        ] or [discord.SelectOption(label="Aucune notification", value="none")]
        super().__init__(placeholder="Choisir une notification", options=options, row=2)

    async def callback(self, interaction):
        if self.values[0] != "none":
            self.owner.selected_notification = int(self.values[0])
        await self.owner.refresh(interaction)


class NotificationChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, view):
        self.owner = view
        super().__init__(
            placeholder="Salon de notification", min_values=1, max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news], row=3,
        )

    async def callback(self, interaction):
        await self.owner.bot.db.execute(
            "UPDATE social_notifications SET discord_channel_id = ? WHERE guild_id = ? AND id = ?",
            (self.values[0].id, self.owner.guild.id, self.owner.selected_notification),
        )
        await self.owner.refresh(interaction)


class NotificationRoleSelect(discord.ui.RoleSelect):
    def __init__(self, view):
        self.owner = view
        super().__init__(placeholder="Rôle mentionné", min_values=1, max_values=1, row=4)

    async def callback(self, interaction):
        await self.owner.bot.db.execute(
            "UPDATE social_notifications SET role_id = ? WHERE guild_id = ? AND id = ?",
            (self.values[0].id, self.owner.guild.id, self.owner.selected_notification),
        )
        await self.owner.refresh(interaction)


class AiModal(discord.ui.Modal, title="Limites IA"):
    cooldown = discord.ui.TextInput(label="Cooldown (secondes)", default="8", max_length=4)
    per_minute = discord.ui.TextInput(label="Requêtes par minute", default="6", max_length=4)
    daily = discord.ui.TextInput(label="Requêtes par jour", default="50", max_length=6)

    def __init__(self, view):
        super().__init__()
        self.owner = view

    async def on_submit(self, interaction):
        try:
            values = (
                max(0, min(3600, int(str(self.cooldown.value)))),
                max(1, min(1000, int(str(self.per_minute.value)))),
                max(1, min(100000, int(str(self.daily.value)))),
            )
        except ValueError:
            return await interaction.response.send_message(embed=embeds.error("Utilisez uniquement des nombres."), ephemeral=True)
        await self.owner.ensure_ai()
        await self.owner.bot.db.execute(
            "UPDATE ai_settings SET cooldown_seconds = ?, per_minute_limit = ?, daily_limit = ?, "
            "updated_at = strftime('%s','now') WHERE guild_id = ?",
            (*values, self.owner.guild.id),
        )
        await interaction.response.edit_message(embed=await self.owner.build_embed(), view=self.owner)


class SetupView(discord.ui.View):
    def __init__(self, bot, guild, author_id):
        super().__init__(timeout=900)
        self.bot, self.guild, self.author_id = bot, guild, int(author_id)
        self.category = self.selected_log = self.selected_ticket = self.selected_notification = None

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=embeds.error("Ce panneau appartient à une autre personne."), ephemeral=True)
            return False
        if not await _can_setup(self.bot, interaction.user, interaction.guild):
            await _permission_error(interaction)
            return False
        return True

    async def audit(self, user_id, action, value):
        try:
            await self.bot.db.execute(
                "INSERT INTO setup_history (guild_id, user_id, module, action, new_value, created_at) "
                "VALUES (?, ?, ?, ?, ?, strftime('%s','now'))",
                (self.guild.id, user_id, self.category or "home", action, None if value is None else str(value)),
            )
        except Exception:
            pass

    async def ensure_ai(self):
        await self.bot.db.execute(
            "INSERT INTO ai_settings (guild_id) VALUES (?) ON CONFLICT(guild_id) DO NOTHING", (self.guild.id,)
        )

    async def refresh(self, interaction):
        self.render()
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    def render(self):
        self.clear_items()
        self.add_item(CategorySelect(self))
        home = discord.ui.Button(label="Accueil", style=discord.ButtonStyle.secondary, row=1)
        refresh = discord.ui.Button(label="Actualiser", style=discord.ButtonStyle.secondary, row=1)
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger, row=1)

        async def go_home(interaction):
            self.category = self.selected_log = self.selected_ticket = self.selected_notification = None
            await self.refresh(interaction)

        async def do_refresh(interaction):
            await self.refresh(interaction)

        async def do_close(interaction):
            self.clear_items()
            await interaction.response.edit_message(
                embed=embeds.neutral("SentriX — Configuration", "Panneau fermé."), view=self
            )
            self.stop()

        home.callback, refresh.callback, close.callback = go_home, do_refresh, do_close
        self.add_item(home); self.add_item(refresh); self.add_item(close)

        if self.category == "moderation":
            self.add_item(FieldRoleSelect(self, "mod_role", "Rôle staff", 2))
            self.add_item(FieldRoleSelect(self, "mute_role", "Rôle mute", 3))
            self.add_item(FieldRoleSelect(self, "warn_role", "Rôle warn", 4))
        elif self.category == "security":
            self.add_item(AutomodSelect(self))
        elif self.category == "logs":
            self.add_item(LogSelect(self))
            if self.selected_log:
                self.add_item(LogChannelSelect(self))
                toggle = discord.ui.Button(label="Activer / désactiver ce log", style=discord.ButtonStyle.primary, row=4)

                async def toggle_log(interaction):
                    setting = await log_service.get_log_setting(self.bot, self.guild.id, self.selected_log)
                    await self.bot.db.execute(
                        "UPDATE log_settings SET enabled = ?, updated_at = strftime('%s','now') WHERE guild_id = ? AND log_type = ?",
                        (0 if setting.get("enabled") else 1, self.guild.id, self.selected_log),
                    )
                    await self.refresh(interaction)

                toggle.callback = toggle_log
                self.add_item(toggle)
        elif self.category == "welcome":
            self.add_item(FieldChannelSelect(self, "welcome_channel", "Salon de bienvenue", 2))
            self.add_item(FieldChannelSelect(self, "goodbye_channel", "Salon de départ", 3))
            self.add_item(FieldRoleSelect(self, "autorole", "Rôle automatique", 4))
        elif self.category == "roles":
            self.add_item(FieldRoleSelect(self, "autorole", "Autorole", 2))
            self.add_item(FieldRoleSelect(self, "verify_role", "Rôle vérifié", 3))
            self.add_item(FieldRoleSelect(self, "member_role", "Rôle membre", 4))
        elif self.category == "levels":
            self.add_item(FieldChannelSelect(self, "level_channel", "Salon des notifications de niveau", 2))
        elif self.category == "ai":
            toggle = discord.ui.Button(label="Activer / désactiver l’IA", style=discord.ButtonStyle.primary, row=2)
            limits = discord.ui.Button(label="Modifier les limites", style=discord.ButtonStyle.secondary, row=2)

            async def toggle_ai(interaction):
                await self.ensure_ai()
                row = await self.bot.db.fetchone("SELECT enabled FROM ai_settings WHERE guild_id = ?", (self.guild.id,))
                await self.bot.db.execute(
                    "UPDATE ai_settings SET enabled = ?, updated_at = strftime('%s','now') WHERE guild_id = ?",
                    (0 if _get(row, "enabled", 1) else 1, self.guild.id),
                )
                await self.refresh(interaction)

            async def edit_ai(interaction):
                await interaction.response.send_modal(AiModal(self))

            toggle.callback, limits.callback = toggle_ai, edit_ai
            self.add_item(toggle); self.add_item(limits)

    async def prepare(self):
        if self.category == "tickets":
            rows = await self.bot.db.fetchall("SELECT id, name FROM ticket_types WHERE guild_id = ? ORDER BY id", (self.guild.id,))
            self.add_item(TicketSelect(self, rows))
            if self.selected_ticket:
                self.add_item(TicketCategorySelect(self)); self.add_item(TicketRoleSelect(self))
        elif self.category == "notifications":
            rows = await self.bot.db.fetchall(
                "SELECT id, platform, source_url FROM social_notifications WHERE guild_id = ? ORDER BY id", (self.guild.id,)
            )
            self.add_item(NotificationSelect(self, rows))
            if self.selected_notification:
                self.add_item(NotificationChannelSelect(self)); self.add_item(NotificationRoleSelect(self))

    async def build_embed(self):
        await self.prepare()
        conf = await self.bot.db.get_guild_config(self.guild.id)
        statuses = await module_statuses(self.bot, self.guild, conf)
        if self.category is None:
            active = sum(state == ConfigState.ACTIVE for state, _, _ in statuses.values())
            panel = embeds.brand("SentriX — Configuration", "Configurez les fonctionnalités de SentriX pour ce serveur.")
            panel.add_field(name="Serveur", value=self.guild.name, inline=False)
            panel.add_field(name="Modules actifs", value=f"{active} / {len(statuses)}", inline=True)
            panel.add_field(name="Configuration", value=f"{_completion(statuses)} % terminée", inline=True)
            panel.add_field(
                name="Modules",
                value="\n".join(f"**{CATEGORIES[key][0]}** — {statuses[key][0].value}" for key in CATEGORY_ORDER),
                inline=False,
            )
            errors = [(key, data) for key, data in statuses.items() if data[0] == ConfigState.ERROR]
            if errors:
                panel.add_field(
                    name="À corriger",
                    value="\n".join(f"**{CATEGORIES[key][0]}** — {data[2][0]}" for key, data in errors)[:1024],
                    inline=False,
                )
            panel.set_footer(text="SentriX • Centre de configuration • Choisissez une catégorie")
            return panel

        state, summary, problems = statuses[self.category]
        title, description = CATEGORIES[self.category]
        panel = embeds.brand(f"SentriX — {title}", description)
        panel.add_field(name="État", value=f"**{state.value}**", inline=True)
        panel.add_field(name="Configuration", value=summary, inline=True)

        me = self.guild.me
        perms = me.guild_permissions if me else discord.Permissions.none()
        lines = []
        missing = []
        for permission in BOT_PERMS[self.category]:
            label = PERM_LABELS.get(permission, permission)
            if getattr(perms, permission, False):
                lines.append(f"{label} : OK")
            else:
                lines.append(f"{label} : MANQUANT"); missing.append(label)
        panel.add_field(name="Permissions SentriX", value="\n".join(lines), inline=False)
        if problems:
            panel.add_field(name="Problèmes détectés", value="\n".join(problems)[:1024], inline=False)

        if self.category == "moderation":
            panel.add_field(
                name="Rôles",
                value=f"**Staff :** {_role(self.guild, _get(conf, 'mod_role'))}\n"
                      f"**Mute :** {_role(self.guild, _get(conf, 'mute_role'))}\n"
                      f"**Warn :** {_role(self.guild, _get(conf, 'warn_role'))}",
                inline=False,
            )
            panel.add_field(name="Fonctions", value="Warn • timeout/mute • ban • kick • clear • raisons • DM de sanction", inline=False)
        elif self.category == "security":
            row = await self.bot.db.fetchone("SELECT * FROM automod_settings WHERE guild_id = ?", (self.guild.id,))
            panel.add_field(
                name="Protections",
                value="\n".join(f"**{label} :** {'ACTIF' if _get(row, field, 0) else 'INACTIF'}" for field, label in AUTOMOD),
                inline=False,
            )
        elif self.category == "logs":
            lines = []
            for log_type, meta in log_service.LOG_TYPES.items():
                if meta.get("emits"):
                    setting = await log_service.get_log_setting(self.bot, self.guild.id, log_type)
                    lines.append(
                        f"**{meta['category']} :** {'ACTIF' if setting.get('enabled') else 'INACTIF'} — "
                        f"{_channel(self.guild, setting.get('channel_id'))}"
                    )
            panel.add_field(name="Types de logs", value="\n".join(lines)[:1024], inline=False)
        elif self.category == "tickets":
            panels = await self.bot.db.fetchall(
                "SELECT name, channel_id, enabled FROM ticket_panels_v2 WHERE guild_id = ? ORDER BY id", (self.guild.id,)
            )
            panel.add_field(
                name="Panels",
                value="\n".join(
                    f"**{_get(row, 'name', 'Panel')} :** {'ACTIF' if _get(row, 'enabled', 1) else 'INACTIF'} — "
                    f"{_channel(self.guild, _get(row, 'channel_id'))}" for row in panels
                )[:1024] or "Aucun panel configuré.",
                inline=False,
            )
            if self.selected_ticket:
                row = await self.bot.db.fetchone(
                    "SELECT * FROM ticket_types WHERE guild_id = ? AND id = ?", (self.guild.id, self.selected_ticket)
                )
                if row:
                    panel.add_field(
                        name=f"Type — {_get(row, 'name', 'Ticket')}",
                        value=f"**Catégorie :** {_channel(self.guild, _get(row, 'category_id'))}\n"
                              f"**Support :** {_role(self.guild, _get(row, 'staff_role_id'))}\n"
                              f"**Ping support :** {'ACTIF' if _get(row, 'mention_staff', 1) else 'INACTIF'}\n"
                              f"**Limite :** {_get(row, 'max_per_member', 1)} ticket(s)\n"
                              f"**Fermeture auto :** {_get(row, 'autoclose_hours', 0)} h",
                        inline=False,
                    )
            panel.add_field(
                name="Avancé",
                value="Création de panels/types, formulaires, message d’ouverture, claim et transcript : `+ticketsetup` / `/ticketsetup`.",
                inline=False,
            )
        elif self.category == "welcome":
            panel.add_field(
                name="Configuration",
                value=f"**Bienvenue :** {_channel(self.guild, _get(conf, 'welcome_channel'))}\n"
                      f"**Départ :** {_channel(self.guild, _get(conf, 'goodbye_channel'))}\n"
                      f"**Autorole :** {_role(self.guild, _get(conf, 'autorole'))}\n"
                      f"**Image :** {'Configurée' if _get(conf, 'welcome_image_url') else 'Non configurée'}",
                inline=False,
            )
        elif self.category == "roles":
            rewards = await self.bot.db.fetchall("SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level", (self.guild.id,))
            panel.add_field(
                name="Rôles",
                value=f"**Autorole :** {_role(self.guild, _get(conf, 'autorole'))}\n"
                      f"**Vérifié :** {_role(self.guild, _get(conf, 'verify_role'))}\n"
                      f"**Membre :** {_role(self.guild, _get(conf, 'member_role'))}",
                inline=False,
            )
            panel.add_field(
                name="Récompenses",
                value="\n".join(f"Niveau **{_get(row, 'level')}** → {_role(self.guild, _get(row, 'role_id'))}" for row in rewards)[:1024]
                      or "Aucune récompense.",
                inline=False,
            )
        elif self.category == "levels":
            panel.add_field(
                name="Niveaux",
                value=f"**Salon level-up :** {_channel(self.guild, _get(conf, 'level_channel'))}\n"
                      f"**Multiplicateur XP :** {_get(conf, 'xp_multiplier', 1.0)}\n"
                      f"**Message :** {'Personnalisé' if _get(conf, 'level_message') else 'Par défaut'}",
                inline=False,
            )
            panel.add_field(
                name="Conservation",
                value="XP, niveau, messages, argent, banque et statistiques restent sauvegardés si un membre quitte ou est banni.",
                inline=False,
            )
        elif self.category == "notifications":
            rows = await self.bot.db.fetchall(
                "SELECT id, platform, discord_channel_id, role_id, enabled FROM social_notifications WHERE guild_id = ? ORDER BY id",
                (self.guild.id,),
            )
            panel.add_field(
                name="Sources",
                value="\n".join(
                    f"**{str(_get(row, 'platform', 'notification')).title()} #{_get(row, 'id')} :** "
                    f"{'ACTIF' if _get(row, 'enabled', 1) else 'INACTIF'} — "
                    f"{_channel(self.guild, _get(row, 'discord_channel_id'))} — {_role(self.guild, _get(row, 'role_id'))}"
                    for row in rows
                )[:1024] or "Aucune notification configurée.",
                inline=False,
            )
            panel.add_field(name="Ajouter une source", value="Utilisez `+notifs-ping` pour ajouter une nouvelle URL YouTube/Twitch/TikTok.", inline=False)
        elif self.category == "ai":
            row = await self.bot.db.fetchone("SELECT * FROM ai_settings WHERE guild_id = ?", (self.guild.id,))
            panel.add_field(
                name="Paramètres",
                value=f"**Conversation :** {'ACTIF' if _get(row, 'enabled', 1) else 'INACTIF'}\n"
                      f"**Cooldown :** {_get(row, 'cooldown_seconds', 8)} s\n"
                      f"**Par minute :** {_get(row, 'per_minute_limit', 6)}\n"
                      f"**Par jour :** {_get(row, 'daily_limit', 50)}\n"
                      f"**Mémoire :** {'ACTIF' if _get(row, 'memory_enabled', 1) else 'INACTIF'}",
                inline=False,
            )
            panel.add_field(name="Images", value="La génération d’images garde ses permissions et limites propres.", inline=False)

        if missing:
            panel.add_field(name="À corriger", value="Accordez uniquement les permissions manquantes au rôle SentriX.", inline=False)
        panel.set_footer(text="SentriX • Configuration • Les modifications sont enregistrées immédiatement")
        return panel


class OfficialSetup(commands.Cog, name="SentriXSetup"):
    def __init__(self, bot):
        self.bot = bot

    async def send_setup(self, target):
        guild = getattr(target, "guild", None)
        member = getattr(target, "author", None) or getattr(target, "user", None)
        if not await _can_setup(self.bot, member, guild):
            return await _permission_error(target)
        view = SetupView(self.bot, guild, member.id)
        view.render()
        panel = await view.build_embed()
        if isinstance(target, commands.Context):
            return await target.send(embed=panel, view=view)
        return await target.response.send_message(embed=panel, view=view)

    @commands.command(name="setup")
    async def prefix_setup(self, ctx):
        await self.send_setup(ctx)

    @app_commands.command(name="setup", description="Ouvrir le centre de configuration SentriX")
    async def slash_setup(self, interaction):
        await self.send_setup(interaction)


async def install(bot):
    if bot.get_cog("SentriXSetup") is not None:
        return
    old = bot.get_command("setup")
    if old is not None:
        bot.remove_command("setup")
    bot.tree.remove_command("setup", type=discord.AppCommandType.chat_input)
    await bot.add_cog(OfficialSetup(bot))
    bot._sentrix_setup_owner = "cogs.setup_control_center"


async def setup(bot):
    await install(bot)
