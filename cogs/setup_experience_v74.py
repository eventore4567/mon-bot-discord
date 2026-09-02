"""SentriX V74 — Setup simplifié, permissions Discord natives et tickets complets.

Objectifs :
- Sécurité : un seul bouton Activer / Désactiver. SentriX applique son profil recommandé.
- Permissions : aucune ACL manuelle dans le Setup principal ; les commandes s'appuient sur
  les permissions Discord réelles et la hiérarchie des rôles.
- Tickets : configuration rapide fonctionnelle + accès direct à l'éditeur complet existant
  (texte, image, couleur, types/boutons, formulaires, support, salons, logs, etc.).
- Modération : plus de "rôle staff" ambigu. On peut préparer un vrai rôle Discord de
  modération avec un profil de permissions et, optionnellement, l'attribuer à un membre.
  Les rôles "mute" et "warn" deviennent des badges automatiques réellement utilisés.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels
from . import security_verification_v71 as security_v71
from . import setup_components_v73 as v73
from . import setup_control_center as setup_ui
from . import setup_ticket_autoconfig_v72 as v72
from . import setup_v2_core as core

logger = logging.getLogger("bot.setup-experience-v74")

RUNTIME_MARKER = "Setup Experience V74"

CATEGORY_ORDER = (
    "moderation",
    "security",
    "tickets",
    "welcome",
    "roles",
    "logs",
    "levels",
    "notifications",
    "ai",
)

CATEGORY_META = dict(v73.CATEGORY_META)
CATEGORY_META["moderation"] = (
    "🛡️",
    "Modération",
    "Permissions Discord réelles, profils de modération et badges de sanctions.",
)
CATEGORY_META["security"] = (
    "🔒",
    "Sécurité",
    "Un seul interrupteur : SentriX applique automatiquement le profil recommandé.",
)
CATEGORY_META["tickets"] = (
    "🎫",
    "Tickets",
    "Configuration rapide ou personnalisation complète du panel et de tous ses boutons.",
)

SECURITY_BOT_PERMISSIONS = (
    ("view_channel", "Voir les salons"),
    ("send_messages", "Envoyer des messages"),
    ("embed_links", "Intégrer des liens"),
    ("read_message_history", "Voir l’historique"),
    ("manage_messages", "Gérer les messages"),
    ("moderate_members", "Exclure temporairement des membres"),
    ("kick_members", "Expulser des membres"),
    ("ban_members", "Bannir des membres"),
    ("manage_channels", "Gérer les salons"),
    ("manage_roles", "Gérer les rôles"),
    ("manage_guild", "Gérer le serveur"),
    ("manage_webhooks", "Gérer les webhooks"),
    ("view_audit_log", "Voir le journal d’audit"),
)

MODERATION_PROFILES: dict[str, tuple[str, tuple[str, ...]]] = {
    "helper": (
        "Helper",
        (
            "manage_messages",
            "manage_nicknames",
        ),
    ),
    "moderator": (
        "Modérateur",
        (
            "manage_messages",
            "manage_nicknames",
            "moderate_members",
            "kick_members",
            "move_members",
        ),
    ),
    "senior": (
        "Responsable modération",
        (
            "manage_messages",
            "manage_nicknames",
            "moderate_members",
            "kick_members",
            "ban_members",
            "move_members",
            "manage_channels",
        ),
    ),
}


def _bot_permission_audit(guild: discord.Guild) -> tuple[list[str], list[str]]:
    me = guild.me
    if me is None:
        return [], ["SentriX n’est pas visible comme membre du serveur."]
    ok: list[str] = []
    missing: list[str] = []
    perms = me.guild_permissions
    for attr, label in SECURITY_BOT_PERMISSIONS:
        (ok if getattr(perms, attr, False) else missing).append(label)
    return ok, missing


def _role_from_config(guild: discord.Guild, value: Any) -> discord.Role | None:
    try:
        role = guild.get_role(int(value)) if value else None
    except (TypeError, ValueError):
        return None
    if role is None or role.is_default() or role.managed:
        return None
    return role


async def _set_optional_role(view: "SentriXSetupV74", field: str, role: discord.Role | None) -> None:
    await view.bot.db.set_guild_config(view.guild.id, field, role.id if role else None)


async def _sync_sanction_badge(
    bot: commands.Bot,
    guild: discord.Guild,
    member: discord.Member,
    *,
    action: str,
) -> None:
    """Applique les badges optionnels après une sanction réellement exécutée."""
    conf = await bot.db.get_guild_config(guild.id)
    field = None
    add = True
    if action == "mute":
        field = "mute_role"
    elif action == "unmute":
        field = "mute_role"
        add = False
    elif action == "warn":
        field = "warn_role"

    if field is None:
        return
    role = _role_from_config(guild, setup_ui._get(conf, field))
    if role is None:
        return

    me = guild.me
    if me is None or not me.guild_permissions.manage_roles or role >= me.top_role:
        return
    try:
        if add and role not in member.roles:
            await member.add_roles(role, reason=f"SentriX V74 : badge automatique {action}")
        elif not add and role in member.roles:
            await member.remove_roles(role, reason=f"SentriX V74 : retrait badge automatique {action}")
    except discord.HTTPException:
        logger.debug("Impossible de synchroniser le badge %s", field, exc_info=True)


def _install_moderation_badge_sync(bot: commands.Bot) -> None:
    cog = bot.get_cog("Moderation")
    if cog is None:
        return
    cls = cog.__class__
    current = getattr(cls, "log_sanction", None)
    if current is None or getattr(current, "_sentrix_v74_badges", False):
        return

    async def log_sanction_v74(self, ctx, action, target, reason, duration_seconds=None, extra_fields=None):
        result = await current(
            self,
            ctx,
            action,
            target,
            reason,
            duration_seconds=duration_seconds,
            extra_fields=extra_fields,
        )
        if isinstance(target, discord.Member) and ctx.guild is not None:
            await _sync_sanction_badge(self.bot, ctx.guild, target, action=action)
        return result

    log_sanction_v74._sentrix_v74_badges = True
    log_sanction_v74._sentrix_previous = current
    cls.log_sanction = log_sanction_v74


class SentriXSetupV74(v73.SentriXSetupV73):
    """Dernière façade du Setup : simple pour la sécurité, complète pour les tickets."""

    def __init__(self, bot: commands.Bot, guild: discord.Guild, author_id: int):
        super().__init__(bot, guild, author_id)
        self.moderation_role_id: int | None = None
        self.moderation_member_id: int | None = None
        self.moderation_profile = "moderator"

    async def _effective_states(self) -> dict[str, str]:
        states = await super()._effective_states()

        states["moderation"] = (
            "● ACTIF"
            if await core.module_enabled(self.bot, self.guild.id, "moderation")
            else "○ INACTIF"
        )
        states["security"] = (
            "● ACTIF"
            if await core.module_enabled(self.bot, self.guild.id, "security")
            else "○ INACTIF"
        )
        if await core.module_enabled(self.bot, self.guild.id, "tickets"):
            states["tickets"] = (
                "● ACTIF"
                if await v72.ticket_configuration_ready(self.bot, self.guild)
                else "— À CONFIGURER"
            )
        else:
            states["tickets"] = "○ INACTIF"
        states.pop("permissions", None)
        return states

    async def _build_home(self) -> None:
        self.backend.category = None
        states = await self._effective_states()
        active = sum(
            "ACTIF" in value and "INACTIF" not in value
            for key, value in states.items()
            if key in CATEGORY_ORDER
        )
        problems = sum("CORRIGER" in states.get(key, "") for key in CATEGORY_ORDER)

        container = discord.ui.Container(accent_colour=v73.ACCENT)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "# Configuration de SentriX\n"
                    f"Configurez **{self.guild.name}** sans toucher à des réglages techniques inutiles.\n"
                    f"**{active}/{len(CATEGORY_ORDER)} modules actifs**"
                    + (f" · **{problems} à corriger**" if problems else "")
                    + "\nLes permissions des commandes sont vérifiées directement avec Discord."
                ),
                accessory=v73._thumbnail(self.bot),
            )
        )

        for index, key in enumerate(CATEGORY_ORDER):
            emoji, label, description = CATEGORY_META[key]
            state = v73._short_state(states.get(key, "—"))
            button = discord.ui.Button(label="Configurer", style=discord.ButtonStyle.secondary)

            async def open_page(interaction: discord.Interaction, category=key):
                self.page = category
                self.backend = self._new_backend(category)
                await self.refresh(interaction)

            button.callback = open_page
            container.add_item(
                discord.ui.Section(
                    discord.ui.TextDisplay(f"## {emoji} {label}\n{description}\n**{state}**"),
                    accessory=button,
                )
            )
            if index in {1, 4}:
                container.add_item(discord.ui.Separator())

        refresh = discord.ui.Button(label="Actualiser", style=discord.ButtonStyle.secondary, emoji="🔄")
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger)

        async def do_refresh(interaction: discord.Interaction):
            await self.refresh(interaction)

        async def do_close(interaction: discord.Interaction):
            await self._close(interaction)

        refresh.callback = do_refresh
        close.callback = do_close
        container.add_item(discord.ui.ActionRow(refresh, close))
        self.add_item(container)

    async def _build_page(self, page: str) -> None:
        if page == "security":
            return await self._build_security()
        if page == "tickets":
            return await self._build_tickets()
        if page == "moderation":
            return await self._build_moderation()
        return await super()._build_page(page)

    def _add_navigation(self, container: discord.ui.Container) -> None:
        back = discord.ui.Button(label="Retour", style=discord.ButtonStyle.primary, emoji="↩️")
        refresh = discord.ui.Button(label="Actualiser", style=discord.ButtonStyle.secondary, emoji="🔄")
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger)

        async def go_back(interaction: discord.Interaction):
            self.page = None
            self.backend = self._new_backend(None)
            await self.refresh(interaction)

        async def do_refresh(interaction: discord.Interaction):
            await self.refresh(interaction)

        async def do_close(interaction: discord.Interaction):
            await self._close(interaction)

        back.callback = go_back
        refresh.callback = do_refresh
        close.callback = do_close
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.ActionRow(back, refresh, close))

    async def _set_security_profile(self, enabled: bool, actor_id: int) -> None:
        await self.bot.db.execute(
            "INSERT INTO automod_settings(guild_id) VALUES(?) ON CONFLICT(guild_id) DO NOTHING",
            (self.guild.id,),
        )
        columns = ", ".join(f"{field} = ?" for field, _label in setup_ui.AUTOMOD)
        values = tuple(1 if enabled else 0 for _ in setup_ui.AUTOMOD)
        await self.bot.db.execute(
            f"UPDATE automod_settings SET {columns} WHERE guild_id = ?",
            (*values, self.guild.id),
        )
        await security_v71.ensure_schema(self.bot)
        await security_v71.update_setting(
            self.bot, self.guild.id, "honeypot_enabled", int(enabled), actor_id
        )
        await security_v71.update_setting(
            self.bot, self.guild.id, "verification_enabled", int(enabled), actor_id
        )
        if enabled:
            await security_v71.update_setting(
                self.bot, self.guild.id, "raid_intensity", "normal", actor_id
            )
            await security_v71.update_setting(
                self.bot,
                self.guild.id,
                "verification_threshold",
                security_v71.DEFAULT_SCORE_THRESHOLD,
                actor_id,
            )
        await self.bot.db.execute(
            "INSERT INTO honeypot_verification(guild_id,enabled,created_at) "
            "VALUES(?,?,strftime('%s','now')) "
            "ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled",
            (self.guild.id, int(enabled)),
        )
        security_v71._invalidate_automod(self.bot, self.guild.id)
        await core.set_module_enabled(
            self.bot,
            self.guild.id,
            "security",
            enabled,
            actor_id=actor_id,
        )
        runtime = getattr(self.bot, "_sentrix_security_v71_runtime", None)
        if runtime is not None:
            try:
                await runtime.refresh_gateway_panels(self.guild)
            except Exception:
                logger.debug("Rafraîchissement des panneaux sécurité indisponible", exc_info=True)

    async def _build_security(self) -> None:
        enabled = await core.module_enabled(self.bot, self.guild.id, "security")
        _ok, missing = _bot_permission_audit(self.guild)
        status = discord.ui.Button(
            label="Activé" if enabled else "Désactivé",
            style=discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary,
            disabled=True,
        )
        container = discord.ui.Container(accent_colour=v73.ACCENT)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "# 🔒 Sécurité\n"
                    "Ici il n’y a plus 15 menus : **un seul bouton**.\n"
                    "Quand la sécurité est activée, SentriX applique automatiquement son profil "
                    "anti-spam, anti-raid, anti-liens, anti-invitations, anti-bot, anti-scam, "
                    "anti-nuke, honeypot et vérification.\n\n"
                    "Les utilisateurs sont autorisés selon leurs **permissions Discord réelles** "
                    "et la hiérarchie des rôles."
                ),
                accessory=v73._thumbnail(self.bot),
            )
        )
        container.add_item(discord.ui.Separator())
        perm_text = (
            "### Permissions du bot\n✅ Les permissions nécessaires sont disponibles."
            if not missing
            else "### Permissions du bot\n⚠️ Il manque : " + ", ".join(missing[:12])
        )
        container.add_item(discord.ui.Section(discord.ui.TextDisplay(perm_text), accessory=status))

        toggle = discord.ui.Button(
            label="Désactiver la sécurité" if enabled else "Activer la sécurité",
            style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success,
        )

        async def toggle_security(interaction: discord.Interaction):
            if not interaction.response.is_done():
                await interaction.response.defer()
            await self._set_security_profile(not enabled, interaction.user.id)
            await self.refresh(interaction)

        toggle.callback = toggle_security
        container.add_item(discord.ui.ActionRow(toggle))
        self._add_navigation(container)
        self.add_item(container)

    async def _build_tickets(self) -> None:
        enabled = await core.module_enabled(self.bot, self.guild.id, "tickets")
        ready = await v72.ticket_configuration_ready(self.bot, self.guild)
        panneaux, panel, types = await v72._existing_ticket_rows(self.bot, self.guild.id)
        status_label = "Activé" if enabled and ready else "À configurer" if enabled else "Désactivé"
        status_style = (
            discord.ButtonStyle.success
            if enabled and ready
            else discord.ButtonStyle.secondary
        )
        status = discord.ui.Button(label=status_label, style=status_style, disabled=True)
        container = discord.ui.Container(accent_colour=v73.ACCENT)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "# 🎫 Tickets\n"
                    "Vous pouvez partir du **réglage par défaut** en un clic ou tout personnaliser : "
                    "titre, texte, couleur, image, miniature, salon, rôle support, catégorie, logs, "
                    "formulaire, message d’ouverture et boutons.\n\n"
                    "**Un type de ticket = un bouton** en mode boutons. Discord permet jusqu’à "
                    "**25 options par panel** ; vous pouvez créer plusieurs panneaux si nécessaire."
                ),
                accessory=v73._thumbnail(self.bot),
            )
        )
        container.add_item(discord.ui.Separator())
        summary = (
            f"### Configuration actuelle\n"
            f"Panels : **{len(panneaux)}** · Types/boutons : **{len(types)}**\n"
            + (
                f"Panel principal : **{v72._row_get(panel, 'name', 'Panel')}**"
                if panel is not None
                else "Aucun panel créé."
            )
        )
        container.add_item(discord.ui.Section(discord.ui.TextDisplay(summary), accessory=status))

        quick = discord.ui.Button(
            label="Configuration rapide / réparer",
            style=discord.ButtonStyle.success,
            emoji="⚡",
        )
        full = discord.ui.Button(
            label="Tout personnaliser",
            style=discord.ButtonStyle.primary,
            emoji="🛠️",
        )
        toggle = discord.ui.Button(
            label="Désactiver" if enabled else "Activer avec les réglages par défaut",
            style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success,
        )

        async def quick_config(interaction: discord.Interaction):
            if not interaction.response.is_done():
                await interaction.response.defer()
            try:
                result = await v72.ensure_ticket_configuration(
                    self.bot,
                    self.guild,
                    actor_id=interaction.user.id,
                )
                role = result.get("role")
                if (
                    isinstance(interaction.user, discord.Member)
                    and isinstance(role, discord.Role)
                    and role not in interaction.user.roles
                    and self.guild.me is not None
                    and self.guild.me.guild_permissions.manage_roles
                    and role < self.guild.me.top_role
                ):
                    try:
                        await interaction.user.add_roles(
                            role,
                            reason="SentriX V74 : le configurateur devient Support par défaut",
                        )
                    except discord.HTTPException:
                        logger.debug("Impossible d'attribuer le rôle Support au configurateur", exc_info=True)
                await self.refresh(interaction)
                await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.success('Tickets prêts. Le panel par défaut a été créé/réparé et publié. Vous pouvez maintenant le personnaliser sans repartir de zéro.')), ephemere=True)
            except v72.TicketBootstrapError as exc:
                await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.error(str(exc))), ephemere=True)

        async def full_config(interaction: discord.Interaction):
            ticket_cog = self.bot.get_cog("Tickets")
            if ticket_cog is None:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Le module Tickets n’est pas chargé.')), ephemere=True)
            ticket_runtime = v72._tickets_module()
            panel_embed = embeds.neutral(
                "Configuration complète des tickets",
                "Créez autant de panneaux et de types que nécessaire. "
                "Vous pouvez modifier le texte, l’image, la couleur, les boutons, "
                "les formulaires, les salons et les rôles.",
            )
            await interaction.response.send_message(
                embed=panel_embed,
                view=ticket_runtime.TicketSetupHubView(ticket_cog, interaction.user.id),
                ephemeral=True,
            )

        async def toggle_tickets(interaction: discord.Interaction):
            if not interaction.response.is_done():
                await interaction.response.defer()
            if enabled:
                await core.set_module_enabled(
                    self.bot,
                    self.guild.id,
                    "tickets",
                    False,
                    actor_id=interaction.user.id,
                )
                await self.refresh(interaction)
            else:
                try:
                    await v72.ensure_ticket_configuration(
                        self.bot,
                        self.guild,
                        actor_id=interaction.user.id,
                    )
                    await self.refresh(interaction)
                except v72.TicketBootstrapError as exc:
                    await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.error(str(exc))), ephemere=True)

        quick.callback = quick_config
        full.callback = full_config
        toggle.callback = toggle_tickets
        container.add_item(discord.ui.ActionRow(quick, full))
        container.add_item(discord.ui.ActionRow(toggle))
        self._add_navigation(container)
        self.add_item(container)

    async def _build_moderation(self) -> None:
        enabled = await core.module_enabled(self.bot, self.guild.id, "moderation")
        conf = await self.bot.db.get_guild_config(self.guild.id)
        mute_role = _role_from_config(self.guild, setup_ui._get(conf, "mute_role"))
        warn_role = _role_from_config(self.guild, setup_ui._get(conf, "warn_role"))
        status = discord.ui.Button(
            label="Activé" if enabled else "Désactivé",
            style=discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary,
            disabled=True,
        )

        container = discord.ui.Container(accent_colour=v73.ACCENT)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "# 🛡️ Modération\n"
                    "Le vieux **« Rôle staff »** n’est plus demandé. SentriX décide l’accès avec "
                    "les permissions Discord réelles : timeout, kick, ban, gérer les messages, "
                    "les salons, les rôles, etc.\n\n"
                    "Vous pouvez aussi préparer un rôle avec un profil de permissions ci-dessous "
                    "et l’attribuer directement à un membre."
                ),
                accessory=v73._thumbnail(self.bot),
            )
        )
        container.add_item(discord.ui.Separator())
        badge_text = (
            "### Badges automatiques de sanction\n"
            f"Rôle après mute : **{mute_role.name if mute_role else 'Aucun'}**\n"
            f"Rôle après warn : **{warn_role.name if warn_role else 'Aucun'}**\n"
            "Le rôle mute est retiré automatiquement avec `unmute`."
        )
        container.add_item(discord.ui.Section(discord.ui.TextDisplay(badge_text), accessory=status))

        toggle = discord.ui.Button(
            label="Désactiver la modération" if enabled else "Activer la modération",
            style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success,
        )

        async def toggle_moderation(interaction: discord.Interaction):
            if not interaction.response.is_done():
                await interaction.response.defer()
            await core.set_module_enabled(
                self.bot,
                self.guild.id,
                "moderation",
                not enabled,
                actor_id=interaction.user.id,
            )
            await self.refresh(interaction)

        toggle.callback = toggle_moderation
        container.add_item(discord.ui.ActionRow(toggle))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay("### Créer / préparer un vrai rôle de modération"))

        role_select = discord.ui.RoleSelect(
            placeholder="1. Rôle Discord à configurer",
            min_values=1,
            max_values=1,
        )
        profile_select = discord.ui.Select(
            placeholder="2. Niveau de permissions",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=label,
                    value=key,
                    description=(
                        "Messages et pseudos"
                        if key == "helper"
                        else "Mute, kick, messages, vocal"
                        if key == "moderator"
                        else "Modération complète sans Administrateur"
                    ),
                )
                for key, (label, _flags) in MODERATION_PROFILES.items()
            ],
        )
        member_select = discord.ui.UserSelect(
            placeholder="3. Membre à ajouter au rôle (optionnel)",
            min_values=0,
            max_values=1,
        )

        async def pick_role(interaction: discord.Interaction):
            self.moderation_role_id = role_select.values[0].id
            await interaction.response.defer()

        async def pick_profile(interaction: discord.Interaction):
            self.moderation_profile = profile_select.values[0]
            await interaction.response.defer()

        async def pick_member(interaction: discord.Interaction):
            self.moderation_member_id = member_select.values[0].id if member_select.values else None
            await interaction.response.defer()

        role_select.callback = pick_role
        profile_select.callback = pick_profile
        member_select.callback = pick_member
        container.add_item(discord.ui.ActionRow(role_select))
        container.add_item(discord.ui.ActionRow(profile_select))
        container.add_item(discord.ui.ActionRow(member_select))

        apply_profile = discord.ui.Button(
            label="Appliquer les permissions et attribuer le rôle",
            style=discord.ButtonStyle.success,
        )

        async def apply_moderation_profile(interaction: discord.Interaction):
            role = self.guild.get_role(self.moderation_role_id) if self.moderation_role_id else None
            if role is None or role.is_default() or role.managed:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Choisissez un rôle Discord modifiable.')), ephemere=True)
            me = self.guild.me
            if me is None or not me.guild_permissions.manage_roles:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('SentriX a besoin de **Gérer les rôles** pour faire cela.')), ephemere=True)
            if role >= me.top_role:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Placez le rôle SentriX au-dessus du rôle à configurer.')), ephemere=True)

            _label, flags = MODERATION_PROFILES.get(
                self.moderation_profile,
                MODERATION_PROFILES["moderator"],
            )
            missing_for_bot = [flag for flag in flags if not getattr(me.guild_permissions, flag, False)]
            if missing_for_bot:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('SentriX ne peut pas accorder des permissions qu’il ne possède pas lui-même : ' + ', '.join(missing_for_bot))), ephemere=True)

            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            permissions = role.permissions
            permissions.update(**{flag: True for flag in flags})
            try:
                await role.edit(
                    permissions=permissions,
                    reason=f"SentriX V74 : profil {self.moderation_profile}",
                )
                await self.bot.db.set_guild_config(self.guild.id, "mod_role", role.id)
                assigned = False
                if self.moderation_member_id:
                    member = self.guild.get_member(self.moderation_member_id)
                    if member is not None and role not in member.roles:
                        await member.add_roles(role, reason="SentriX V74 : attribution du rôle de modération")
                        assigned = True
                await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.success(f'Le rôle **{role.name}** utilise maintenant le profil **{MODERATION_PROFILES[self.moderation_profile][0]}**.' + (' Il a aussi été attribué au membre choisi.' if assigned else ''))), ephemere=True)
            except discord.HTTPException:
                await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.error('Discord a refusé la modification du rôle. Vérifiez la hiérarchie.')), ephemere=True)

        apply_profile.callback = apply_moderation_profile
        container.add_item(discord.ui.ActionRow(apply_profile))

        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay("### Rôles automatiques après sanction (optionnels)"))

        mute_select = discord.ui.RoleSelect(
            placeholder="Rôle à donner pendant un mute",
            min_values=0,
            max_values=1,
        )
        warn_select = discord.ui.RoleSelect(
            placeholder="Rôle à donner après un warn",
            min_values=0,
            max_values=1,
        )

        async def set_mute_role(interaction: discord.Interaction):
            role = mute_select.values[0] if mute_select.values else None
            await _set_optional_role(self, "mute_role", role)
            await self.refresh(interaction)

        async def set_warn_role(interaction: discord.Interaction):
            role = warn_select.values[0] if warn_select.values else None
            await _set_optional_role(self, "warn_role", role)
            await self.refresh(interaction)

        mute_select.callback = set_mute_role
        warn_select.callback = set_warn_role
        container.add_item(discord.ui.ActionRow(mute_select))
        container.add_item(discord.ui.ActionRow(warn_select))

        self._add_navigation(container)
        self.add_item(container)


async def _send_setup_v74(self, target):
    guild = getattr(target, "guild", None)
    member = getattr(target, "author", None) or getattr(target, "user", None)
    if not await setup_ui._can_setup(self.bot, member, guild):
        return await setup_ui._permission_error(target)

    view = SentriXSetupV74(self.bot, guild, member.id)
    await view.prepare()

    if isinstance(target, commands.Context):
        return await target.send(view=view)
    if target.response.is_done():
        return await target.followup.send(view=view)
    return await target.response.send_message(view=view)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_setup_experience_v74", False):
        return

    current = setup_ui.OfficialSetup.send_setup
    if not getattr(current, "_sentrix_setup_v74", False):
        _send_setup_v74._sentrix_setup_v74 = True
        _send_setup_v74._sentrix_previous = current
        setup_ui.OfficialSetup.send_setup = _send_setup_v74

    _install_moderation_badge_sync(bot)
    bot._sentrix_setup_experience_v74 = True
    logger.info(
        "%s installé : sécurité simple, permissions Discord natives, tickets complets et modération claire.",
        RUNTIME_MARKER,
    )


__all__ = ["SentriXSetupV74", "install"]
