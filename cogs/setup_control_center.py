"""Centre de configuration officiel de SentriX.

Le nouveau +setup et /setup utilisent le même contrôleur, modifient toujours le même
message et lisent les configurations historiques au lieu de les recréer.
"""
from __future__ import annotations

import re
from enum import Enum

import discord
from discord import app_commands
from discord.ext import commands

from utils import checks, embeds, log_service, sentrix_panels as panels


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
    "logs": ("view_channel", "send_messages", "embed_links", "attach_files", "read_message_history", "view_audit_log"),
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
    "read_message_history": "Lire l’historique des messages",
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
                ok, reason = log_service.validate_channel(guild, channel.id, needs_file=True)
                if not ok:
                    log_errors.append(f"{meta['category']} : {reason}.")
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
        category = self.owner.selected_log
        channel_id = self.values[0].id if self.values else None
        if channel_id is not None:
            ok, reason = log_service.validate_channel(
                self.owner.guild,
                channel_id,
                needs_file=True,
            )
            if not ok:
                return await interaction.response.send_message(
                    embed=embeds.error(
                        f"Ce salon ne peut pas recevoir les logs SentriX : **{reason}**."
                    ),
                    ephemeral=True,
                )

        await log_service.set_log_config(
            self.owner.bot,
            self.owner.guild.id,
            category,
            channel_id=channel_id,
            enabled=channel_id is not None,
        )
        saved = await log_service.get_log_config(
            self.owner.bot,
            self.owner.guild.id,
            category,
        )
        if channel_id is not None and (
            saved is None or int(saved.get("channel_id") or 0) != int(channel_id)
        ):
            return await interaction.response.send_message(
                embed=embeds.error(
                    "La configuration du salon de logs n’a pas été enregistrée correctement."
                ),
                ephemeral=True,
            )
        await self.owner.audit(interaction.user.id, category, channel_id)
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
        await self.owner.composer()
        await interaction.response.edit_message(
            content=None, embeds=[], view=self.owner, attachments=self.owner.fichiers()
        )


class SetupView(discord.ui.LayoutView):
    """Centre de controle SentriX, compose.

    C'etait une View classique qui remplacait un embed a champs. Le contenu et les
    commandes vivent maintenant dans le MEME conteneur : banniere en tete, etat
    general, sections par sujet, puis les selecteurs et boutons sous l'accent de
    couleur. Une LayoutView ne se modifie pas en place, donc chaque action
    recompose le conteneur — aucun reste de l'ecran precedent ne subsiste.
    """

    def __init__(self, bot, guild, author_id):
        super().__init__(timeout=900)
        self.bot, self.guild, self.author_id = bot, guild, int(author_id)
        self.category = self.selected_log = self.selected_ticket = self.selected_notification = None
        self._commandes: list = []

    # -- collecte des composants -------------------------------------------
    def ajouter(self, item) -> None:
        """Remplace self.add_item : les composants vont dans le conteneur."""
        self._commandes.append(item)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                embed=embeds.error("Ce panneau appartient à une autre personne."), ephemeral=True
            )
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
        await self.composer()
        await interaction.response.edit_message(
            content=None, embeds=[], view=self, attachments=self.fichiers()
        )

    def fichiers(self):
        fichier = panels.fichier_banniere(self.intention())
        return [fichier] if fichier is not None else []

    def intention(self) -> str:
        """La configuration a sa propre famille de banniere : c'est un domaine."""
        return "configuration"

    # -- composition --------------------------------------------------------
    async def composer(self) -> None:
        """Compose le panneau a partir de l'embed produit par TOUTE la chaine.

        Douze modules enrichissent SetupView.build_embed : verification, honeypot,
        permissions, langue, tickets, polish... Porter chacun vers un nouveau
        contrat aurait ete douze occasions de casser le setup. On garde donc
        build_embed comme contrat — chaque couche continue d'y ajouter ses champs —
        et c'est le RESULTAT FINAL qui devient un panneau : titre, resume, puis une
        section par champ, chacune precedee de son filet.
        """
        self.clear_items()
        self._commandes = []
        self.render()
        await self.prepare()

        # Les douze couches appellent self.add_item : sur une LayoutView, cela
        # place le composant AU NIVEAU DE LA VUE, donc au-dessus du conteneur et
        # au-dessus de la banniere. On les recupere pour les remettre dedans.
        recuperes = [
            item for item in list(self.children)
            if not isinstance(item, (discord.ui.Container, discord.ui.ActionRow))
        ]
        for item in recuperes:
            self.remove_item(item)
        self._commandes = _sans_doublons(self._commandes + recuperes)
        self.clear_items()

        embed = await self.build_embed()
        titre = str(getattr(embed, "title", "") or "SentriX — Centre de contrôle")
        resume = _sans_barre(str(getattr(embed, "description", "") or ""))
        sections = [
            panels.Section(str(champ.name or "").strip(), texte=_sans_barre(str(champ.value or "")))
            for champ in getattr(embed, "fields", ())
            if str(champ.value or "").strip()
        ]

        conteneur = discord.ui.Container(
            accent_colour=discord.Colour(panels.INTENTIONS[self.intention()][0])
        )
        galerie = discord.ui.MediaGallery()
        galerie.add_item(media=f"attachment://{panels.nom_banniere(self.intention())}")
        conteneur.add_item(galerie)
        conteneur.add_item(discord.ui.TextDisplay(f"## {titre}\n{resume}"))

        for section in sections:
            rendu = section.rendu()
            if rendu:
                conteneur.add_item(discord.ui.Separator())
                conteneur.add_item(discord.ui.TextDisplay(rendu[:3800]))

        conteneur.add_item(
            discord.ui.TextDisplay("-# SentriX • Configuration · chaque modification est enregistrée aussitôt")
        )
        for rangee in _rangees_de(self._commandes):
            conteneur.add_item(rangee)
        self.add_item(conteneur)

    def render(self):
        self.ajouter(CategorySelect(self))
        home = discord.ui.Button(label="Accueil", style=discord.ButtonStyle.secondary)
        refresh = discord.ui.Button(label="Actualiser", style=discord.ButtonStyle.secondary)
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger)

        async def go_home(interaction):
            self.category = self.selected_log = self.selected_ticket = self.selected_notification = None
            await self.refresh(interaction)

        async def do_refresh(interaction):
            await self.refresh(interaction)

        async def do_close(interaction):
            self.clear_items()
            ferme = panels.Panneau(
                titre="SentriX — Configuration",
                sous_titre="Panneau fermé. Relancez `+setup` pour le rouvrir.",
                kind="configuration",
                pied="SentriX • Configuration",
            )
            await interaction.response.edit_message(
                content=None, embeds=[], view=ferme, attachments=ferme.fichiers()
            )
            self.stop()

        home.callback, refresh.callback, close.callback = go_home, do_refresh, do_close
        self.ajouter(home); self.ajouter(refresh); self.ajouter(close)

        if self.category == "moderation":
            self.ajouter(FieldRoleSelect(self, "mod_role", "Rôle staff", 2))
            self.ajouter(FieldRoleSelect(self, "mute_role", "Rôle mute", 3))
            self.ajouter(FieldRoleSelect(self, "warn_role", "Rôle warn", 4))
        elif self.category == "security":
            self.ajouter(AutomodSelect(self))
        elif self.category == "logs":
            self.ajouter(LogSelect(self))
            if self.selected_log:
                self.ajouter(LogChannelSelect(self))
                toggle = discord.ui.Button(
                    label="Activer / désactiver ce log", style=discord.ButtonStyle.primary
                )

                async def toggle_log(interaction):
                    setting = await log_service.get_log_setting(self.bot, self.guild.id, self.selected_log)
                    channel_id = setting.get("channel_id")
                    if not setting.get("enabled") and not channel_id:
                        return await interaction.response.send_message(
                            embed=embeds.error("Choisissez d’abord un salon pour cette catégorie de logs."),
                            ephemeral=True,
                        )
                    await log_service.set_log_config(
                        self.bot, self.guild.id, self.selected_log,
                        channel_id=channel_id, enabled=not bool(setting.get("enabled")),
                    )
                    await self.refresh(interaction)

                toggle.callback = toggle_log
                self.ajouter(toggle)
        elif self.category == "welcome":
            self.ajouter(FieldChannelSelect(self, "welcome_channel", "Salon de bienvenue", 2))
            self.ajouter(FieldChannelSelect(self, "goodbye_channel", "Salon de départ", 3))
            self.ajouter(FieldRoleSelect(self, "autorole", "Rôle automatique", 4))
        elif self.category == "roles":
            self.ajouter(FieldRoleSelect(self, "autorole", "Autorole", 2))
            self.ajouter(FieldRoleSelect(self, "verify_role", "Rôle vérifié", 3))
            self.ajouter(FieldRoleSelect(self, "member_role", "Rôle membre", 4))
        elif self.category == "levels":
            self.ajouter(FieldChannelSelect(self, "level_channel", "Salon des notifications de niveau", 2))
        elif self.category == "ai":
            toggle = discord.ui.Button(label="Activer / désactiver l’IA", style=discord.ButtonStyle.primary)
            limits = discord.ui.Button(label="Modifier les limites", style=discord.ButtonStyle.secondary)

            async def toggle_ai(interaction):
                await self.ensure_ai()
                row = await self.bot.db.fetchone(
                    "SELECT enabled FROM ai_settings WHERE guild_id = ?", (self.guild.id,)
                )
                await self.bot.db.execute(
                    "UPDATE ai_settings SET enabled = ?, updated_at = strftime('%s','now') WHERE guild_id = ?",
                    (0 if _get(row, "enabled", 1) else 1, self.guild.id),
                )
                await self.refresh(interaction)

            async def edit_ai(interaction):
                await interaction.response.send_modal(AiModal(self))

            toggle.callback, limits.callback = toggle_ai, edit_ai
            self.ajouter(toggle); self.ajouter(limits)

    async def prepare(self):
        if self.category == "tickets":
            rows = await self.bot.db.fetchall(
                "SELECT id, name FROM ticket_types WHERE guild_id = ? ORDER BY id", (self.guild.id,)
            )
            self.ajouter(TicketSelect(self, rows))
            if self.selected_ticket:
                self.ajouter(TicketCategorySelect(self)); self.ajouter(TicketRoleSelect(self))
        elif self.category == "notifications":
            rows = await self.bot.db.fetchall(
                "SELECT id, platform, source_url FROM social_notifications WHERE guild_id = ? ORDER BY id",
                (self.guild.id,),
            )
            self.ajouter(NotificationSelect(self, rows))
            if self.selected_notification:
                self.ajouter(NotificationChannelSelect(self)); self.ajouter(NotificationRoleSelect(self))

    # -- contenu ------------------------------------------------------------
    async def build_embed(self):
        """Embed du centre de controle, base de la chaine des douze couches.

        Le rendu final est un panneau compose, mais le CONTRAT reste un embed :
        c'est lui que les autres modules enrichissent. Chaque section devient un
        champ, et composer() les retransforme en sections apres la chaine.
        """
        conf = await self.bot.db.get_guild_config(self.guild.id)
        statuses = await module_statuses(self.bot, self.guild, conf)
        if self.category is None:
            titre, resume, sections = await self._contenu_accueil(statuses)
        else:
            titre, resume, sections = await self._contenu_categorie(conf, statuses)
        return _embed_de_sections(titre, resume, sections)

    async def _contenu_accueil(self, statuses):
        """Vue d'ensemble : ce qui marche, ce qui manque, ce qui bloque."""
        actifs = sum(state == ConfigState.ACTIVE for state, _, _ in statuses.values())
        pourcentage = _completion(statuses)

        etats = [
            panels.Ligne(
                CATEGORIES[cle][0],
                statuses[cle][0].value,
                indice=statuses[cle][1] if statuses[cle][1] else None,
            )
            for cle in CATEGORY_ORDER
        ]

        sections = [
            panels.Section(
                "État général",
                [
                    panels.Ligne("Configuration", f"**{pourcentage} %** terminée"),
                    panels.Ligne("Modules actifs", f"**{actifs}** sur **{len(statuses)}**"),
                    panels.Ligne("Serveur", self.guild.name),
                ],
            ),
            panels.Section("Modules", etats),
        ]

        # Ce qui bloque passe AVANT le reste : c'est la raison d'ouvrir +setup.
        erreurs = [
            (cle, data) for cle, data in statuses.items() if data[0] == ConfigState.ERROR
        ]
        if erreurs:
            sections.insert(
                0,
                panels.Section(
                    f"À corriger ({len(erreurs)})",
                    [
                        panels.Ligne(CATEGORIES[cle][0], data[2][0] if data[2] else "Configuration incomplète")
                        for cle, data in erreurs
                    ],
                ),
            )

        a_configurer = [
            CATEGORIES[cle][0]
            for cle, data in statuses.items()
            if data[0] == ConfigState.UNCONFIGURED
        ]
        if a_configurer:
            sections.append(
                panels.Section(
                    "Jamais configuré",
                    [panels.Ligne("Modules", " · ".join(a_configurer),
                                  indice="Choisissez-les dans le menu ci-dessous pour les activer.")],
                )
            )

        resume = (
            f"**{pourcentage} %** configuré · **{actifs}/{len(statuses)}** modules actifs"
        )
        if erreurs:
            resume += f" · **{len(erreurs)}** à corriger"
        return "SentriX — Centre de contrôle", resume, sections

    async def _contenu_categorie(self, conf, statuses):
        """Une categorie : son etat, sa configuration reelle, ce qui manque."""
        state, summary, problems = statuses[self.category]
        titre, description = CATEGORIES[self.category]

        sections = [
            panels.Section(
                "État",
                [
                    panels.Ligne("Module", f"**{state.value}**"),
                    panels.Ligne("Configuration", summary or "Aucune"),
                ],
            )
        ]

        if problems:
            sections.append(
                panels.Section(
                    f"Problèmes détectés ({len(problems)})",
                    [panels.Ligne(f"{i}", probleme) for i, probleme in enumerate(problems[:6], 1)],
                )
            )

        # Permissions : on ne liste QUE ce qui manque. Enumerer ce qui marche
        # deja noyait l'information utile au milieu de « OK » repetes.
        moi = self.guild.me
        perms = moi.guild_permissions if moi else discord.Permissions.none()
        manquantes = [
            PERM_LABELS.get(permission, permission)
            for permission in BOT_PERMS[self.category]
            if not getattr(perms, permission, False)
        ]
        if manquantes:
            sections.append(
                panels.Section(
                    f"Permissions manquantes ({len(manquantes)})",
                    [panels.Ligne("SentriX a besoin de", " · ".join(manquantes),
                                  indice="Paramètres du serveur › Rôles › SentriX.")],
                )
            )
        else:
            sections.append(
                panels.Section(
                    "Permissions",
                    [panels.Ligne("SentriX", f"A tout ce qu'il faut pour **{titre.casefold()}**")],
                )
            )

        detail = await self._detail_categorie(conf)
        sections.extend(detail)

        intention_etat = {
            ConfigState.ACTIVE: "actif",
            ConfigState.INACTIVE: "inactif",
            ConfigState.UNCONFIGURED: "jamais configuré",
            ConfigState.ERROR: "à corriger",
        }.get(state, state.value)
        resume = f"{description}\n**État :** {intention_etat}"
        return f"SentriX — {titre}", resume, sections

    async def _detail_categorie(self, conf):
        """Configuration reelle de la categorie : salons, roles, sources."""
        cle = self.category
        if cle == "moderation":
            return [
                panels.Section(
                    "Rôles configurés",
                    [
                        panels.Ligne("Staff", _role(self.guild, _get(conf, "mod_role"))),
                        panels.Ligne("Mute", _role(self.guild, _get(conf, "mute_role"))),
                        panels.Ligne("Avertissements", _role(self.guild, _get(conf, "warn_role"))),
                    ],
                )
            ]
        if cle == "security":
            row = await self.bot.db.fetchone(
                "SELECT * FROM automod_settings WHERE guild_id = ?", (self.guild.id,)
            )
            actives = [label for field, label in AUTOMOD if _get(row, field, 0)]
            inactives = [label for field, label in AUTOMOD if not _get(row, field, 0)]
            sections = [
                panels.Section(
                    f"Protections actives ({len(actives)}/{len(AUTOMOD)})",
                    [panels.Ligne("Modules", " · ".join(actives) if actives else "Aucune")],
                )
            ]
            if inactives:
                sections.append(
                    panels.Section(
                        f"Désactivées ({len(inactives)})",
                        [panels.Ligne("Modules", " · ".join(inactives),
                                      indice="Le menu ci-dessous les active une par une.")],
                    )
                )
            return sections
        if cle == "logs":
            actifs, inactifs = [], []
            for log_type, meta in log_service.LOG_TYPES.items():
                if not meta.get("emits"):
                    continue
                setting = await log_service.get_log_setting(self.bot, self.guild.id, log_type)
                if setting.get("enabled") and setting.get("channel_id"):
                    actifs.append(
                        panels.Ligne(meta["category"], _channel(self.guild, setting.get("channel_id")))
                    )
                else:
                    inactifs.append(meta["category"])
            sections = [
                panels.Section(
                    f"Journaux actifs ({len(actifs)}/{len(actifs) + len(inactifs)})",
                    actifs or [panels.Ligne("Aucun", "Choisissez une catégorie ci-dessous")],
                )
            ]
            if inactifs:
                sections.append(
                    panels.Section(
                        f"Non configurés ({len(inactifs)})",
                        [panels.Ligne("Catégories", " · ".join(inactifs))],
                    )
                )
            return sections
        if cle == "tickets":
            rows = await self.bot.db.fetchall(
                "SELECT name, channel_id, enabled FROM ticket_panels_v2 WHERE guild_id = ? ORDER BY id",
                (self.guild.id,),
            )
            sections = [
                panels.Section(
                    f"Panels ({len(rows)})",
                    [
                        panels.Ligne(
                            _get(row, "name", "Panel"),
                            f"{'actif' if _get(row, 'enabled', 1) else 'inactif'} · "
                            f"{_channel(self.guild, _get(row, 'channel_id'))}",
                        )
                        for row in rows
                    ] or [panels.Ligne("Aucun panel", "`+ticketsetup` en crée un en quelques clics")],
                )
            ]
            if self.selected_ticket:
                row = await self.bot.db.fetchone(
                    "SELECT * FROM ticket_types WHERE guild_id = ? AND id = ?",
                    (self.guild.id, self.selected_ticket),
                )
                if row:
                    sections.append(
                        panels.Section(
                            f"Type — {_get(row, 'name', 'Ticket')}",
                            [
                                panels.Ligne("Catégorie", _channel(self.guild, _get(row, "category_id"))),
                                panels.Ligne("Support", _role(self.guild, _get(row, "staff_role_id"))),
                                panels.Ligne("Ping support", "actif" if _get(row, "mention_staff", 1) else "inactif"),
                                panels.Ligne("Limite par membre", f"{_get(row, 'max_per_member', 1)} ticket(s)"),
                                panels.Ligne("Fermeture auto", f"{_get(row, 'autoclose_hours', 0)} h"),
                            ],
                        )
                    )
            return sections
        if cle == "welcome":
            return [
                panels.Section(
                    "Salons et rôles",
                    [
                        panels.Ligne("Bienvenue", _channel(self.guild, _get(conf, "welcome_channel"))),
                        panels.Ligne("Départ", _channel(self.guild, _get(conf, "goodbye_channel"))),
                        panels.Ligne("Rôle automatique", _role(self.guild, _get(conf, "autorole"))),
                        panels.Ligne(
                            "Image d'accueil",
                            "Configurée" if _get(conf, "welcome_image_url") else "Aucune",
                        ),
                    ],
                )
            ]
        if cle == "roles":
            rewards = await self.bot.db.fetchall(
                "SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level", (self.guild.id,)
            )
            return [
                panels.Section(
                    "Rôles automatiques",
                    [
                        panels.Ligne("Autorole", _role(self.guild, _get(conf, "autorole"))),
                        panels.Ligne("Vérifié", _role(self.guild, _get(conf, "verify_role"))),
                        panels.Ligne("Membre", _role(self.guild, _get(conf, "member_role"))),
                    ],
                ),
                panels.Section(
                    f"Récompenses de niveau ({len(rewards)})",
                    [
                        panels.Ligne(f"Niveau {_get(row, 'level')}", _role(self.guild, _get(row, "role_id")))
                        for row in rewards[:10]
                    ] or [panels.Ligne("Aucune", "`+levelroles` en ajoute une")],
                ),
            ]
        if cle == "levels":
            return [
                panels.Section(
                    "Réglages",
                    [
                        panels.Ligne("Salon des montées", _channel(self.guild, _get(conf, "level_channel"))),
                        panels.Ligne("Multiplicateur XP", str(_get(conf, "xp_multiplier", 1.0))),
                        panels.Ligne(
                            "Message", "Personnalisé" if _get(conf, "level_message") else "Par défaut"
                        ),
                    ],
                ),
                panels.Section(
                    "Conservation des données",
                    [
                        panels.Ligne(
                            "Si un membre part",
                            "XP, niveau, messages et argent sont conservés",
                            indice="Rien n'est perdu s'il revient.",
                        )
                    ],
                ),
            ]
        if cle == "notifications":
            rows = await self.bot.db.fetchall(
                "SELECT id, platform, discord_channel_id, role_id, enabled FROM social_notifications "
                "WHERE guild_id = ? ORDER BY id",
                (self.guild.id,),
            )
            return [
                panels.Section(
                    f"Sources suivies ({len(rows)})",
                    [
                        panels.Ligne(
                            f"{str(_get(row, 'platform', 'source')).title()} #{_get(row, 'id')}",
                            f"{'actif' if _get(row, 'enabled', 1) else 'inactif'} · "
                            f"{_channel(self.guild, _get(row, 'discord_channel_id'))}",
                            indice=f"Rôle mentionné : {_role(self.guild, _get(row, 'role_id'))}"
                            if _get(row, "role_id") else None,
                        )
                        for row in rows[:8]
                    ] or [panels.Ligne("Aucune source", "`+notifs-ping` ajoute une chaîne YouTube, Twitch ou TikTok")],
                )
            ]
        if cle == "ai":
            row = await self.bot.db.fetchone(
                "SELECT * FROM ai_settings WHERE guild_id = ?", (self.guild.id,)
            )
            return [
                panels.Section(
                    "Paramètres",
                    [
                        panels.Ligne("Conversation", "active" if _get(row, "enabled", 1) else "désactivée"),
                        panels.Ligne("Mémoire", "active" if _get(row, "memory_enabled", 1) else "désactivée"),
                    ],
                ),
                panels.Section(
                    "Limites",
                    [
                        panels.Ligne("Délai entre deux questions", f"{_get(row, 'cooldown_seconds', 8)} s"),
                        panels.Ligne("Par minute", str(_get(row, "per_minute_limit", 6))),
                        panels.Ligne("Par jour", str(_get(row, "daily_limit", 50))),
                    ],
                    aligne=True,
                ),
            ]
        return []


_BARRE = re.compile(r"[━─—]{6,}")


def _sans_barre(texte: str) -> str:
    """Retire les barres dessinees des embeds : le panneau a de vrais filets."""
    return _BARRE.sub("", texte).strip()


def _sans_doublons(commandes):
    """Deux couches peuvent ajouter le meme selecteur (la langue, par exemple).

    Dans un embed a champs, le doublon passait inapercu ; dans un conteneur, il
    s'affiche deux fois. On garde le premier de chaque identite.
    """
    vus = set()
    garde = []
    for item in commandes:
        identite = (
            type(item).__name__,
            str(getattr(item, "placeholder", "") or getattr(item, "label", "") or ""),
        )
        if identite in vus:
            continue
        vus.add(identite)
        garde.append(item)
    return garde


def _embed_de_sections(titre: str, resume: str, sections) -> discord.Embed:
    """Sections -> embed. Le pont qui laisse les douze couches travailler."""
    panneau = embeds.brand(titre, resume)
    for section in sections:
        rendu = section.rendu()
        # On retire l'en-tete « ### ◢ TITRE » : il redevient le nom du champ.
        corps = rendu.split("\n", 1)[1] if "\n" in rendu else ""
        if corps.strip():
            panneau.add_field(name=section.titre[:256], value=corps[:1024], inline=False)
    return panneau


def _rangees_de(commandes):
    """Repartit les composants en rangees valides.

    Un menu deroulant occupe seul sa rangee, un bouton en partage jusqu'a cinq.
    Sans cette regle, Discord refuse le message entier.
    """
    rangees = []
    lot = []

    def vider():
        if lot:
            rangees.append(discord.ui.ActionRow(*lot))
            lot.clear()

    for item in commandes:
        if isinstance(item, discord.ui.Button):
            lot.append(item)
            if len(lot) == 5:
                vider()
        else:
            vider()
            rangees.append(discord.ui.ActionRow(item))
    vider()
    return rangees


class OfficialSetup(commands.Cog, name="SentriXSetup"):
    def __init__(self, bot):
        self.bot = bot

    async def send_setup(self, target):
        guild = getattr(target, "guild", None)
        member = getattr(target, "author", None) or getattr(target, "user", None)
        if not await _can_setup(self.bot, member, guild):
            return await _permission_error(target)
        view = SetupView(self.bot, guild, member.id)
        await view.composer()
        return await panels.envoyer(target, view)

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
