"""Staff-only Discord Components V2 panel for vocal member-history configuration."""
from __future__ import annotations

import logging

import discord

from services import voice_history
from utils import log_service

logger = logging.getLogger("bot.voice-history-config")


class VoiceHistoryConfigView(discord.ui.LayoutView):
    def __init__(self, bot, guild: discord.Guild, owner_id: int):
        super().__init__(timeout=600)
        self.bot, self.guild, self.owner_id = bot, guild, int(owner_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        from cogs.setup_control_center import _can_setup
        if interaction.guild_id == self.guild.id and interaction.user.id == self.owner_id:
            if await _can_setup(self.bot, interaction.user, interaction.guild):
                return True
        await interaction.response.send_message(
            "Seul le responsable autorisé peut modifier ces paramètres.",
            ephemeral=True,
        )
        return False

    async def build(self) -> None:
        self.clear_items()
        settings = await voice_history.get_settings(self.bot, self.guild.id)
        route = await log_service.get_log_setting(self.bot, self.guild.id, "voice")
        channel = self.guild.get_channel(int(route["channel_id"])) if route.get("channel_id") else None
        route_on = bool(route["enabled"] and channel)
        container = discord.ui.Container()
        container.add_item(discord.ui.TextDisplay(
            "## 👁️ SentriX · Centre de surveillance\n"
            "Suivi privé de l'activité vocale des membres et des sessions.\n"
            "-# Aucune conversation audio n'est enregistrée."
        ))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            "**🎧 Surveillance vocale · Historique privé**\n"
            f"• Entrées et sorties : **{'Activées' if settings['enabled'] else 'Désactivées'}**\n"
            f"• Déplacements : **{'Activés' if settings['enabled'] and settings['track_moves'] else 'Désactivés'}**\n"
            f"• Durées : **{'Activées' if settings['enabled'] and settings['track_duration'] else 'Désactivées'}**\n"
            "-# Même sans salon de logs public, les sessions activées restent dans le dossier staff."
        ))
        enabled = discord.ui.Button(
            label="⏸ Arrêter le suivi" if settings["enabled"] else "▶ Activer le suivi",
            style=discord.ButtonStyle.secondary,
        )
        moves = discord.ui.Button(
            label="🔁 Déplacements : ON" if settings["track_moves"] else "🔁 Déplacements : OFF",
            style=discord.ButtonStyle.secondary,
        )
        durations = discord.ui.Button(
            label="⏱️ Durées : ON" if settings["track_duration"] else "⏱️ Durées : OFF",
            style=discord.ButtonStyle.secondary,
        )
        async def toggle(interaction, field, old):
            try:
                await voice_history.set_setting(
                    self.bot, self.guild.id, field, not old,
                )
                if field == "enabled" and not old:
                    await voice_history.reconcile_guild(self.bot, self.guild)
            except Exception:
                logger.exception("Voice tracking config failed guild=%s field=%s", self.guild.id, field)
                return await interaction.response.send_message(
                    "Impossible de sauvegarder ce réglage vocal.", ephemeral=True,
                )
            await self.refresh(interaction)

        enabled.callback = lambda i: toggle(i, "enabled", settings["enabled"])
        moves.callback = lambda i: toggle(i, "track_moves", settings["track_moves"])
        durations.callback = lambda i: toggle(i, "track_duration", settings["track_duration"])
        container.add_item(discord.ui.ActionRow(enabled, moves, durations))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            "**📨 Publication dans les salons de logs (facultative)**\n"
            f"• Salon : {channel.mention if channel else 'Non configuré'}\n"
            f"• Publication dans le salon : **{'Activée' if route_on else 'Désactivée'}**\n"
            "-# Indépendant du dossier privé : aucune notification automatique quand le suivi est activé."
        ))
        choose = discord.ui.ChannelSelect(
            placeholder="Choisir ou effacer le salon des logs vocaux",
            channel_types=[discord.ChannelType.text],
            min_values=0, max_values=1,
        )
        choose.callback = self.choose_channel
        container.add_item(discord.ui.ActionRow(choose))
        publish = discord.ui.Button(
            label="🔕 Couper les logs vocaux" if route_on else "📣 Activer les logs vocaux",
            style=discord.ButtonStyle.secondary,
        )
        publish.callback = self.toggle_publishing
        container.add_item(discord.ui.ActionRow(publish))
        container.add_item(discord.ui.TextDisplay(
            "-# Centre Surveillance · Réservé au staff · Durées uniquement pour les sessions "
            "réellement observées. Les connexions antérieures à l'activation ne sont pas reconstituées."
        ))
        self.add_item(container)

    async def refresh(self, interaction):
        await self.build()
        await interaction.response.edit_message(view=self)

    async def choose_channel(self, interaction):
        values = interaction.data.get("values", [])
        target_id = int(values[0]) if values else None
        if target_id:
            valid, message = log_service.validate_channel(self.guild, target_id)
            if not valid:
                return await interaction.response.send_message(
                    "Salon invalide : " + message, ephemeral=True,
                )
        route = await log_service.get_log_setting(self.bot, self.guild.id, "voice")
        await log_service.set_log_config(
            self.bot, self.guild.id, "voice",
            channel_id=target_id,
            enabled=bool(route["enabled"] and target_id),
        )
        await self.refresh(interaction)

    async def toggle_publishing(self, interaction):
        route = await log_service.get_log_setting(self.bot, self.guild.id, "voice")
        channel_id = route.get("channel_id")
        if not route["enabled"] and not channel_id:
            return await interaction.response.send_message(
                "Choisissez d'abord un salon textuel pour les logs vocaux.", ephemeral=True,
            )
        if not route["enabled"]:
            valid, explanation = log_service.validate_channel(self.guild, channel_id)
            if not valid:
                return await interaction.response.send_message(
                    "Le salon n'est pas disponible : " + explanation,
                    ephemeral=True,
                )
        await log_service.set_log_config(
            self.bot, self.guild.id, "voice",
            channel_id=channel_id,
            enabled=not bool(route["enabled"]),
        )
        await self.refresh(interaction)


async def open_voice_history_config(bot, interaction: discord.Interaction):
    from cogs.setup_control_center import _can_setup
    if interaction.guild is None or not await _can_setup(
        bot, interaction.user, interaction.guild,
    ):
        return await interaction.response.send_message(
            "La permission Gérer le serveur est nécessaire.", ephemeral=True,
        )
    view = VoiceHistoryConfigView(bot, interaction.guild, interaction.user.id)
    await view.build()
    await interaction.response.send_message(view=view, ephemeral=True)
