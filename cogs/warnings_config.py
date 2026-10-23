"""Panneau Discord Components V2 des avertissements SentriX.

Réutilise les tables historiques : warnings, sanction_dm_templates, guild_config
et log_config. Aucune sanction n'est déclenchée par une configuration.
"""
from __future__ import annotations

import discord
from cogs.setup_control_center import _can_setup, validate_role_choice, validate_channel_choice
from utils import log_service


async def _authorized(interaction: discord.Interaction, expected: int) -> bool:
    if interaction.user.id == expected and await _can_setup(
        interaction.client, interaction.user, interaction.guild
    ):
        return True
    await interaction.response.send_message(
        "Ce panneau appartient à un autre responsable ou vous n'avez pas la permission Gérer le serveur.",
        ephemeral=True,
    )
    return False


class WarningSettingsView(discord.ui.LayoutView):
    """Administration réelle des warns, en privé et sans modification implicite."""

    def __init__(self, bot, guild, owner_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.guild = guild
        self.owner_id = int(owner_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _authorized(interaction, self.owner_id)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.build()
        await interaction.response.edit_message(view=self)

    async def build(self) -> None:
        self.clear_items()
        conf = await self.bot.db.get_guild_config(self.guild.id)
        threshold = int((conf["warn_ban_threshold"] if conf else 0) or 0)
        role_id = (conf["warn_role"] if conf else None)
        dm_row = await self.bot.db.fetchone(
            "SELECT message, enabled FROM sanction_dm_templates WHERE guild_id=? AND action='warn'",
            (self.guild.id,),
        )
        dm_on = dm_row is None or bool(dm_row["enabled"])
        log = await log_service.get_log_setting(self.bot, self.guild.id, "moderation")
        log_channel = self.guild.get_channel(int(log["channel_id"])) if log.get("channel_id") else None
        recent = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM warnings WHERE guild_id=?", (self.guild.id,)
        )
        count = int(recent["n"] if recent else 0)
        role = self.guild.get_role(int(role_id)) if role_id else None

        card = discord.ui.Container()
        card.add_item(discord.ui.TextDisplay(
            "## ⚠️ SentriX · Centre des avertissements\n"
            "Configurez les sanctions et les notifications depuis Discord."
        ))
        card.add_item(discord.ui.Separator())
        card.add_item(discord.ui.TextDisplay(
            "**📊 État du système**\n"
            f"• Avertissements enregistrés : **{count}**\n"
            f"• Notification privée : **{'Activée' if dm_on else 'Désactivée'}**\n"
            f"• Bannissement automatique : **{'Après '+str(threshold)+' warns' if threshold else 'Désactivé'}**\n"
            f"• Rôle attribué : {role.mention if role else 'Aucun'}\n"
            f"• Journal des sanctions : {log_channel.mention if log_channel else 'Non configuré'}"
        ))
        dm = discord.ui.Button(
            label="🔕 Couper les MP" if dm_on else "✉️ Activer les MP",
            style=discord.ButtonStyle.secondary,
        )
        dm.callback = self.toggle_dm
        history = discord.ui.Button(label="📜 Historique", style=discord.ButtonStyle.secondary)
        history.callback = self.show_history
        card.add_item(discord.ui.ActionRow(dm, history))
        card.add_item(discord.ui.Separator())
        card.add_item(discord.ui.TextDisplay(
            "**⚖️ Escalade des avertissements**\n"
            "Le bannissement automatique reste **OFF par défaut**. "
            "Choisir un seuil l'active volontairement."
        ))
        select = discord.ui.Select(
            placeholder="Seuil de bannissement automatique",
            options=[
                discord.SelectOption(label="Désactivé (recommandé)", value="0", emoji="🛡️", default=threshold==0),
                discord.SelectOption(label="Après 3 avertissements", value="3", default=threshold==3),
                discord.SelectOption(label="Après 5 avertissements", value="5", default=threshold==5),
                discord.SelectOption(label="Après 10 avertissements", value="10", default=threshold==10),
            ],
        )
        select.callback = self.change_threshold
        card.add_item(discord.ui.ActionRow(select))
        card.add_item(discord.ui.TextDisplay("**🎭 Rôle automatique après un avertissement**"))
        role_select = discord.ui.RoleSelect(
            placeholder="Choisir / retirer le rôle averti",
            min_values=0, max_values=1,
        )
        role_select.callback = self.change_role
        card.add_item(discord.ui.ActionRow(role_select))
        card.add_item(discord.ui.TextDisplay("**📋 Salon des logs de modération**"))
        channel_select = discord.ui.ChannelSelect(
            placeholder="Choisir le salon des sanctions",
            channel_types=[discord.ChannelType.text],
            min_values=0, max_values=1,
        )
        channel_select.callback = self.change_log
        card.add_item(discord.ui.ActionRow(channel_select))
        card.add_item(discord.ui.TextDisplay(
            "-# /warn dispose toujours de l'option notifier: true/false. "
            "Le MP général peut être désactivé ici. "
            "Les rôles, dossiers, logs et seuils réutilisent les réglages existants."
        ))
        self.add_item(card)

    async def toggle_dm(self, interaction: discord.Interaction) -> None:
        row = await self.bot.db.fetchone(
            "SELECT message,enabled FROM sanction_dm_templates WHERE guild_id=? AND action='warn'",
            (self.guild.id,),
        )
        enabled_now = row is None or bool(row["enabled"])
        new_value = 0 if enabled_now else 1
        default = (
            "Vous avez reçu un avertissement sur {serveur}.\n"
            "Raison : {raison}\nModérateur : {moderateur}"
        )
        # Conserve le gabarit personnalisé existant, même pendant un OFF.
        msg = str(row["message"] or default) if row else default
        await self.bot.db.execute(
            "INSERT INTO sanction_dm_templates (guild_id,action,message,enabled) VALUES (?,'warn',?,?) "
            "ON CONFLICT(guild_id,action) DO UPDATE SET enabled=excluded.enabled,"
            "message=CASE WHEN LENGTH(sanction_dm_templates.message)>0 THEN sanction_dm_templates.message "
            "ELSE excluded.message END",
            (self.guild.id, msg, new_value),
        )
        await self.refresh(interaction)

    async def change_threshold(self, interaction: discord.Interaction) -> None:
        chosen = int(interaction.data["values"][0])
        if chosen not in {0, 3, 5, 10}:
            return await interaction.response.send_message("Seuil invalide.", ephemeral=True)
        # Le choix d'un seuil positif est explicite. Le choix 0 est sûr par défaut.
        await self.bot.db.set_guild_config(self.guild.id, "warn_ban_threshold", chosen)
        await self.refresh(interaction)

    async def change_role(self, interaction: discord.Interaction) -> None:
        values = interaction.data.get("values", [])
        role = self.guild.get_role(int(values[0])) if values else None
        error = validate_role_choice(self.guild, role, "warn_role")
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        await self.bot.db.set_guild_config(
            self.guild.id, "warn_role", role.id if role else None,
        )
        await self.refresh(interaction)

    async def change_log(self, interaction: discord.Interaction) -> None:
        values = interaction.data.get("values", [])
        channel = self.guild.get_channel(int(values[0])) if values else None
        if channel is not None:
            error = validate_channel_choice(self.guild, channel, "log_channel")
            if error:
                return await interaction.response.send_message(error, ephemeral=True)
        await log_service.set_log_config(
            self.bot, self.guild.id, "moderation",
            channel_id=channel.id if channel else None,
            enabled=bool(channel),
        )
        if channel:
            from cogs import setup_v2_core
            await setup_v2_core.enable_module_if_unset(
                self.bot, self.guild.id, "logs", actor_id=interaction.user.id
            )
        await self.refresh(interaction)

    async def show_history(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT user_id, moderator_id, reason, timestamp FROM warnings "
            "WHERE guild_id=? ORDER BY timestamp DESC LIMIT 8",
            (self.guild.id,),
        )
        lines = [
            f"**<@{r['user_id']}>** · <t:{int(r['timestamp'])}:R> · "
            f"{discord.utils.escape_markdown(str(r['reason'] or 'Aucune raison')[:130])}"
            for r in rows
        ]
        await interaction.response.send_message(
            "📜 **Derniers avertissements**\n" + ("\n".join(lines) if lines else "Aucun avertissement enregistré."),
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )


async def open_warning_config(bot, interaction: discord.Interaction) -> None:
    from cogs.setup_control_center import _can_setup
    if not await _can_setup(bot, interaction.user, interaction.guild):
        return await interaction.response.send_message(
            "Permission Gérer le serveur requise.", ephemeral=True
        )
    view = WarningSettingsView(bot, interaction.guild, interaction.user.id)
    await view.build()
    await interaction.response.send_message(view=view, ephemeral=True)
