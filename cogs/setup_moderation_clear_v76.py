"""SentriX V76 — page Modération plus simple à comprendre.

Cette couche ne change pas la logique de permissions de V74/V75. Elle clarifie seulement
l'interface : on choisit un rôle Discord existant, le niveau de droits à lui ajouter et,
facultativement, un membre qui recevra ce rôle immédiatement.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from utils import embeds
from . import setup_control_center as setup_ui
from . import setup_experience_v74 as v74
from . import setup_v2_core as core

logger = logging.getLogger("bot.setup-moderation-clear-v76")
RUNTIME_MARKER = "Setup Moderation Clear V76"


async def _build_moderation_v76(self: v74.SentriXSetupV74) -> None:
    enabled = await core.module_enabled(self.bot, self.guild.id, "moderation")
    conf = await self.bot.db.get_guild_config(self.guild.id)
    mute_role = v74._role_from_config(self.guild, setup_ui._get(conf, "mute_role"))
    warn_role = v74._role_from_config(self.guild, setup_ui._get(conf, "warn_role"))

    status = discord.ui.Button(
        label="Activé" if enabled else "Désactivé",
        style=discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary,
        disabled=True,
    )

    container = discord.ui.Container(accent_colour=v74.v73.ACCENT)
    container.add_item(
        discord.ui.Section(
            discord.ui.TextDisplay(
                "# 🛡️ Modération\n"
                "SentriX utilise les **permissions Discord du rôle** pour savoir ce qu'un membre "
                "a le droit de faire. Vous n'avez donc pas besoin de configurer chaque commande "
                "une par une.\n\n"
                "La partie ci-dessous sert simplement à **ajouter automatiquement les bonnes "
                "permissions à un rôle Discord existant**."
            ),
            accessory=v74.v73._thumbnail(self.bot),
        )
    )
    container.add_item(discord.ui.Separator())

    state_text = (
        "### État\n"
        f"Modération SentriX : **{'active' if enabled else 'désactivée'}**\n"
        "Les permissions réelles restent contrôlées par Discord et par la hiérarchie des rôles."
    )
    container.add_item(discord.ui.Section(discord.ui.TextDisplay(state_text), accessory=status))

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

    container.add_item(
        discord.ui.TextDisplay(
            "### Donner des droits de modération à un rôle\n"
            "Vous avez déjà un rôle comme **@Modérateur** ? Choisissez-le ici et SentriX ajoute "
            "les permissions correspondant au niveau choisi.\n\n"
            "**1. Choisissez le rôle** qui doit pouvoir modérer.\n"
            "**2. Choisissez ce qu'il pourra faire.**\n"
            "**3. Facultatif : choisissez un membre** si vous voulez lui donner ce rôle tout de suite."
        )
    )

    role_select = discord.ui.RoleSelect(
        placeholder="1. Choisir le rôle (ex. Modérateur)",
        min_values=1,
        max_values=1,
    )
    profile_select = discord.ui.Select(
        placeholder="2. Choisir les droits de ce rôle",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(
                label="Modération légère",
                value="helper",
                description="Gérer les messages et les pseudos.",
            ),
            discord.SelectOption(
                label="Modération standard",
                value="moderator",
                description="Messages, pseudos, timeout, kick et vocal.",
            ),
            discord.SelectOption(
                label="Modération avancée",
                value="senior",
                description="Standard + ban et gestion des salons, sans Administrateur.",
            ),
        ],
    )
    member_select = discord.ui.UserSelect(
        placeholder="3. Donner ce rôle à un membre (facultatif)",
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
        label="Enregistrer les permissions",
        style=discord.ButtonStyle.success,
    )

    async def apply_moderation_profile(interaction: discord.Interaction):
        role = self.guild.get_role(self.moderation_role_id) if self.moderation_role_id else None
        if role is None or role.is_default() or role.managed:
            return await interaction.response.send_message(
                embed=embeds.error("Choisissez d'abord un rôle Discord que SentriX peut modifier."),
                ephemeral=True,
            )

        me = self.guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return await interaction.response.send_message(
                embed=embeds.error(
                    "SentriX a besoin de la permission **Gérer les rôles** pour modifier ce rôle."
                ),
                ephemeral=True,
            )
        if role >= me.top_role:
            return await interaction.response.send_message(
                embed=embeds.error(
                    "Le rôle choisi est placé trop haut. Placez le rôle **SentriX** au-dessus de celui-ci."
                ),
                ephemeral=True,
            )

        profile_key = self.moderation_profile or "moderator"
        profile_label, flags = v74.MODERATION_PROFILES.get(
            profile_key,
            v74.MODERATION_PROFILES["moderator"],
        )
        missing_for_bot = [
            flag for flag in flags if not getattr(me.guild_permissions, flag, False)
        ]
        if missing_for_bot:
            return await interaction.response.send_message(
                embed=embeds.error(
                    "SentriX ne possède pas encore toutes les permissions nécessaires pour "
                    "appliquer ce niveau. Vérifiez les permissions de son rôle Discord."
                ),
                ephemeral=True,
            )

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        permissions = role.permissions
        permissions.update(**{flag: True for flag in flags})
        try:
            await role.edit(
                permissions=permissions,
                reason=f"SentriX V76 : niveau de modération {profile_key}",
            )
            await self.bot.db.set_guild_config(self.guild.id, "mod_role", role.id)

            assigned = False
            if self.moderation_member_id:
                member = self.guild.get_member(self.moderation_member_id)
                if member is not None and role not in member.roles:
                    await member.add_roles(
                        role,
                        reason="SentriX V76 : attribution du rôle de modération",
                    )
                    assigned = True

            message = (
                f"Le rôle **{role.name}** est maintenant configuré en **{profile_label}**."
            )
            if assigned:
                message += " Le rôle a aussi été donné au membre choisi."
            elif self.moderation_member_id is None:
                message += " Aucun membre n'a été choisi : seul le rôle a été configuré."

            await interaction.followup.send(
                embed=embeds.success(message),
                ephemeral=True,
            )
        except discord.HTTPException:
            await interaction.followup.send(
                embed=embeds.error(
                    "Discord a refusé la modification. Vérifiez que le rôle SentriX est au-dessus "
                    "du rôle choisi et qu'il possède les permissions nécessaires."
                ),
                ephemeral=True,
            )

    apply_profile.callback = apply_moderation_profile
    container.add_item(discord.ui.ActionRow(apply_profile))

    container.add_item(discord.ui.Separator())
    container.add_item(
        discord.ui.TextDisplay(
            "### Rôles ajoutés automatiquement après une sanction (facultatif)\n"
            "Ces rôles **ne donnent pas accès aux commandes de modération**. Ils servent seulement "
            "de badge automatique : SentriX peut en ajouter un pendant un mute ou après un warn."
        )
    )

    mute_select = discord.ui.RoleSelect(
        placeholder="Badge temporaire donné pendant un mute",
        min_values=0,
        max_values=1,
    )
    warn_select = discord.ui.RoleSelect(
        placeholder="Badge donné automatiquement après un warn",
        min_values=0,
        max_values=1,
    )

    async def set_mute_role(interaction: discord.Interaction):
        role = mute_select.values[0] if mute_select.values else None
        await v74._set_optional_role(self, "mute_role", role)
        await self.refresh(interaction)

    async def set_warn_role(interaction: discord.Interaction):
        role = warn_select.values[0] if warn_select.values else None
        await v74._set_optional_role(self, "warn_role", role)
        await self.refresh(interaction)

    mute_select.callback = set_mute_role
    warn_select.callback = set_warn_role
    container.add_item(discord.ui.ActionRow(mute_select))
    container.add_item(discord.ui.ActionRow(warn_select))

    current_badges = (
        "**Actuellement :** "
        f"mute → **{mute_role.name if mute_role else 'aucun badge'}** · "
        f"warn → **{warn_role.name if warn_role else 'aucun badge'}**"
    )
    container.add_item(discord.ui.TextDisplay(current_badges))

    self._add_navigation(container)
    self.add_item(container)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_setup_moderation_clear_v76", False):
        return

    cls = v74.SentriXSetupV74
    current = cls._build_moderation
    if not getattr(current, "_sentrix_moderation_clear_v76", False):
        _build_moderation_v76._sentrix_moderation_clear_v76 = True
        _build_moderation_v76._sentrix_previous = current
        cls._build_moderation = _build_moderation_v76

    v74.CATEGORY_META["moderation"] = (
        "🛡️",
        "Modération",
        "Choisissez un rôle et son niveau de droits ; SentriX applique les permissions Discord.",
    )

    bot._sentrix_setup_moderation_clear_v76 = True
    logger.info("%s installé : page Modération simplifiée et explicitée.", RUNTIME_MARKER)


__all__ = ["install"]
