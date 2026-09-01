"""Composants réutilisables du setup SentriX V20."""
from __future__ import annotations

import discord

from utils import embeds, log_service
from utils.control_center_v20_meta import SECURITY_FIELDS, STATE_ACTIVE, STATE_INACTIVE, _row_get


class SetupResourcePicker(discord.ui.View):
    def __init__(self, parent: "SetupControlView", *, kind: str, action: str, label: str):
        super().__init__(timeout=120)
        self.parent = parent
        self.kind = kind
        self.action = action
        self.label = label
        if kind == "role":
            picker = discord.ui.RoleSelect(placeholder=f"Choisir : {label}", min_values=1, max_values=1)
        else:
            channel_types = [discord.ChannelType.text]
            if action == "tickets_category":
                channel_types = [discord.ChannelType.category]
            picker = discord.ui.ChannelSelect(
                placeholder=f"Choisir : {label}", min_values=1, max_values=1,
                channel_types=channel_types,
            )
        picker.callback = self._picked
        self.add_item(picker)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.parent.interaction_check(interaction)

    async def _picked(self, interaction: discord.Interaction):
        value = self.children[0].values[0]
        try:
            await self.parent.apply_resource(interaction, self.kind, self.action, value)
        except ValueError as exc:
            return await interaction.response.edit_message(
                embed=embeds.error(str(exc) or "Ce réglage n’est pas valide."), view=self
            )
        except discord.HTTPException:
            return await interaction.response.edit_message(
                embed=embeds.error(
                    "Discord a refusé cette modification. Vérifiez les permissions de SentriX."
                ),
                view=self,
            )
        for child in self.children:
            child.disabled = True
        try:
            await interaction.response.edit_message(
                embed=embeds.success(f"{self.label} mis à jour."), view=self
            )
        except discord.InteractionResponded:
            pass
        await self.parent.refresh_main()


class NumberModal(discord.ui.Modal):
    def __init__(
        self, parent: "SetupControlView", action: str, title: str, label: str,
        default: str = "",
    ):
        super().__init__(title=title)
        self.parent = parent
        self.action = action
        self.value_input = discord.ui.TextInput(label=label, default=default, max_length=8)
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(str(self.value_input.value).strip())
        except ValueError:
            return await interaction.response.send_message(
                embed=embeds.error("La valeur doit être un nombre entier."), ephemeral=True
            )
        try:
            await self.parent.apply_number(interaction, self.action, value)
        except ValueError as exc:
            return await interaction.response.send_message(
                embed=embeds.error(str(exc) or "Valeur hors limite."), ephemeral=True
            )
        await interaction.response.send_message(
            embed=embeds.success("Réglage enregistré."), ephemeral=True
        )
        await self.parent.refresh_main()


class WelcomeTextModal(discord.ui.Modal, title="Bienvenue et départ"):
    def __init__(self, parent: "SetupControlView", conf):
        super().__init__()
        self.parent = parent
        self.welcome = discord.ui.TextInput(
            label="Message de bienvenue", style=discord.TextStyle.paragraph,
            required=False, max_length=1000,
            default=str(_row_get(conf, "welcome_message", "") or ""),
        )
        self.goodbye = discord.ui.TextInput(
            label="Message de départ", style=discord.TextStyle.paragraph,
            required=False, max_length=1000,
            default=str(_row_get(conf, "goodbye_message", "") or ""),
        )
        self.image = discord.ui.TextInput(
            label="URL image de bienvenue (optionnel)", required=False, max_length=500,
            default=str(_row_get(conf, "welcome_image_url", "") or ""),
        )
        self.add_item(self.welcome)
        self.add_item(self.goodbye)
        self.add_item(self.image)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = self.parent.guild_id
        await self.parent.bot.db.set_guild_config(
            guild_id, "welcome_message", str(self.welcome.value) or None
        )
        await self.parent.bot.db.set_guild_config(
            guild_id, "goodbye_message", str(self.goodbye.value) or None
        )
        await self.parent.bot.db.set_guild_config(
            guild_id, "welcome_image_url", str(self.image.value) or None
        )
        await self.parent.log_change(
            interaction.user.id, "Bienvenue", "messages et image modifiés"
        )
        await interaction.response.send_message(
            embed=embeds.success("Messages de bienvenue et départ mis à jour."),
            ephemeral=True,
        )
        await self.parent.refresh_main()


class SanctionDmModal(discord.ui.Modal, title="Message privé de sanction"):
    def __init__(self, parent: "SetupControlView"):
        super().__init__()
        self.parent = parent
        self.action_input = discord.ui.TextInput(
            label="Action : ban, tempban, kick, mute, warn, unban, unmute", max_length=20
        )
        self.message_input = discord.ui.TextInput(
            label="Message (vide = désactiver)", style=discord.TextStyle.paragraph,
            required=False, max_length=1900,
        )
        self.add_item(self.action_input)
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        action = str(self.action_input.value).strip().casefold()
        allowed = {"ban", "tempban", "kick", "mute", "warn", "unban", "unmute"}
        if action not in allowed:
            return await interaction.response.send_message(
                embed=embeds.error("Action inconnue."), ephemeral=True
            )
        message = str(self.message_input.value)
        await self.parent.bot.db.execute(
            "INSERT INTO sanction_dm_templates (guild_id, action, message, enabled) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(guild_id, action) DO UPDATE SET "
            "message=excluded.message, enabled=excluded.enabled",
            (self.parent.guild_id, action, message, 1 if message.strip() else 0),
        )
        await self.parent.log_change(
            interaction.user.id, "Modération", f"MP sanction {action} modifié"
        )
        await interaction.response.send_message(
            embed=embeds.success("Message privé de sanction mis à jour."), ephemeral=True
        )
        await self.parent.refresh_main()


class SecurityToggleView(discord.ui.View):
    def __init__(self, parent: "SetupControlView"):
        super().__init__(timeout=120)
        self.parent = parent
        self.select = discord.ui.Select(
            placeholder="Choisir une protection à activer/désactiver",
            options=[
                discord.SelectOption(label=label, value=field_name)
                for field_name, label in SECURITY_FIELDS.items()
            ],
        )
        self.select.callback = self._toggle
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.parent.interaction_check(interaction)

    async def _toggle(self, interaction: discord.Interaction):
        field_name = self.select.values[0]
        current = await self.parent.bot.db.get_automod(self.parent.guild_id)
        enabled = bool(_row_get(current, field_name, 0))
        await self.parent.bot.db.execute(
            f"INSERT INTO automod_settings (guild_id, {field_name}) VALUES (?, ?) "
            f"ON CONFLICT(guild_id) DO UPDATE SET {field_name}=excluded.{field_name}",
            (self.parent.guild_id, 0 if enabled else 1),
        )
        await self.parent.log_change(
            interaction.user.id, "Sécurité", f"{field_name}={'off' if enabled else 'on'}"
        )
        await interaction.response.edit_message(
            embed=embeds.success(
                f"{SECURITY_FIELDS[field_name]} : {STATE_INACTIVE if enabled else STATE_ACTIVE}"
            ),
            view=self,
        )
        await self.parent.refresh_main()


class LogTypeSelectView(discord.ui.View):
    def __init__(self, parent: "SetupControlView", mode: str):
        super().__init__(timeout=120)
        self.parent = parent
        self.mode = mode
        self.select = discord.ui.Select(
            placeholder="Choisir un type de log",
            options=[
                discord.SelectOption(label=meta["label"][:100], value=key)
                for key, meta in log_service.LOG_TYPES.items()
            ],
        )
        self.select.callback = self._selected
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.parent.interaction_check(interaction)

    async def _selected(self, interaction: discord.Interaction):
        log_type = self.select.values[0]
        if self.mode == "toggle":
            setting = await log_service.get_log_setting(
                self.parent.bot, self.parent.guild_id, log_type
            )
            if not setting["enabled"] and not setting["channel_id"]:
                return await interaction.response.send_message(
                    embed=embeds.error(
                        "Choisissez d’abord un salon pour ce type de log."
                    ),
                    ephemeral=True,
                )
            await log_service.set_log_enabled(
                self.parent.bot, self.parent.guild_id, log_type,
                not setting["enabled"],
            )
            await self.parent.log_change(
                interaction.user.id, "Logs",
                f"{log_type}={'off' if setting['enabled'] else 'on'}",
            )
            await interaction.response.edit_message(
                embed=embeds.success(
                    f"{log_service.LOG_TYPES[log_type]['label']} : "
                    f"{STATE_INACTIVE if setting['enabled'] else STATE_ACTIVE}"
                ),
                view=self,
            )
            await self.parent.refresh_main()
            return
        picker = SetupResourcePicker(
            self.parent, kind="channel", action=f"log_channel:{log_type}",
            label=log_service.LOG_TYPES[log_type]["label"],
        )
        await interaction.response.send_message(
            embed=embeds.neutral(
                "Choisir un salon",
                "Le salon sélectionné sera enregistré sans supprimer les anciennes configurations.",
            ),
            view=picker,
            ephemeral=True,
        )
