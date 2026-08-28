"""Conversation IA sans mot-clé, limitée à des salons explicitement configurés.

Le listener historique de ``cogs.ai`` reste propriétaire de ``sentrix ...`` et des
mentions. Cette couche ne traite QUE les messages ordinaires dans les salons que
l'administrateur a sélectionnés dans +setup > IA.
"""
from __future__ import annotations

import re
import time

import discord
from discord.ext import commands

import config
from utils import ai_service, embeds
from . import setup_control_center as setup_ui
from . import setup_v2_core as core
from . import setup_v2_ui

_NAME_TRIGGER = re.compile(r"^(?:sentrix|ssentrix|sentri|snetri|snentrix)\b", re.IGNORECASE)


async def ensure_schema(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_ai_bare_v3_schema", False):
        return
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_bare_chat_settings_v3 (
            guild_id INTEGER PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0,
            updated_by INTEGER,
            updated_at INTEGER NOT NULL
        )
        """
    )
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_bare_chat_channels_v3 (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, channel_id)
        )
        """
    )
    bot._sentrix_ai_bare_v3_schema = True


async def bare_settings(bot: commands.Bot, guild_id: int) -> dict:
    await ensure_schema(bot)
    row = await bot.db.fetchone(
        "SELECT enabled FROM ai_bare_chat_settings_v3 WHERE guild_id=?", (guild_id,)
    )
    channels = await bot.db.fetchall(
        "SELECT channel_id FROM ai_bare_chat_channels_v3 WHERE guild_id=? ORDER BY channel_id",
        (guild_id,),
    )
    return {
        "enabled": bool(row["enabled"]) if row else False,
        "channel_ids": [int(item["channel_id"]) for item in channels],
    }


async def set_bare_enabled(bot: commands.Bot, guild_id: int, enabled: bool, actor_id: int) -> None:
    await ensure_schema(bot)
    await bot.db.execute(
        "INSERT INTO ai_bare_chat_settings_v3 (guild_id,enabled,updated_by,updated_at) VALUES (?,?,?,?) "
        "ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled,updated_by=excluded.updated_by,updated_at=excluded.updated_at",
        (guild_id, 1 if enabled else 0, actor_id, int(time.time())),
    )


async def set_bare_channels(bot: commands.Bot, guild_id: int, channel_ids: list[int], actor_id: int) -> None:
    await ensure_schema(bot)
    unique = sorted({int(channel_id) for channel_id in channel_ids})[:5]
    await bot.db.execute("DELETE FROM ai_bare_chat_channels_v3 WHERE guild_id=?", (guild_id,))
    for channel_id in unique:
        await bot.db.execute(
            "INSERT OR IGNORE INTO ai_bare_chat_channels_v3 (guild_id,channel_id) VALUES (?,?)",
            (guild_id, channel_id),
        )
    # Sélectionner volontairement un salon active le mode : aucune activation implicite
    # n'est possible sans choix explicite de l'administrateur.
    if unique:
        await set_bare_enabled(bot, guild_id, True, actor_id)


class BareChatManageView(discord.ui.View):
    def __init__(self, setup_view, author_id: int):
        super().__init__(timeout=240)
        self.setup_view = setup_view
        self.bot = setup_view.bot
        self.guild = setup_view.guild
        self.author_id = author_id

        channels = discord.ui.ChannelSelect(
            placeholder="Salons où SentriX répond à « salut » sans mention",
            min_values=1,
            max_values=5,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=1,
        )

        async def channel_callback(interaction: discord.Interaction):
            await set_bare_channels(
                self.bot,
                self.guild.id,
                [channel.id for channel in channels.values],
                interaction.user.id,
            )
            await interaction.response.send_message(
                embed=embeds.success(
                    "Conversation sans mention activée dans : "
                    + ", ".join(channel.mention for channel in channels.values)
                    + "."
                ),
                ephemeral=True,
            )

        channels.callback = channel_callback
        self.add_item(channels)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Activer / Désactiver", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, interaction: discord.Interaction, _button: discord.ui.Button):
        current = await bare_settings(self.bot, self.guild.id)
        if not current["channel_ids"] and not current["enabled"]:
            return await interaction.response.send_message(
                "Choisissez d’abord au moins un salon. Le mode ne s’active jamais sur tout le serveur par défaut.",
                ephemeral=True,
            )
        await set_bare_enabled(self.bot, self.guild.id, not current["enabled"], interaction.user.id)
        await interaction.response.send_message(
            f"Conversation sans mention : {'ACTIF' if not current['enabled'] else 'INACTIF'}.",
            ephemeral=True,
        )

    @discord.ui.button(label="Retirer tous les salons", style=discord.ButtonStyle.danger, row=0)
    async def clear(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await set_bare_channels(self.bot, self.guild.id, [], interaction.user.id)
        await set_bare_enabled(self.bot, self.guild.id, False, interaction.user.id)
        await interaction.response.send_message(
            "Tous les salons ont été retirés et la conversation sans mention est désactivée.",
            ephemeral=True,
        )


class BareNaturalRuntime:
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._busy: set[tuple[int, int]] = set()

    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or message.webhook_id is not None:
            return
        content = (message.content or "").strip()
        if not content:
            return

        # Les commandes et les anciens déclencheurs restent au moteur historique.
        prefix = (
            self.bot.prefix_cache.get(message.guild.id, config.DEFAULT_PREFIX)
            if hasattr(self.bot, "prefix_cache")
            else config.DEFAULT_PREFIX
        )
        if prefix and content.startswith(prefix):
            return
        if self.bot.user is not None and self.bot.user in message.mentions:
            return
        if _NAME_TRIGGER.match(content):
            return

        values = await bare_settings(self.bot, message.guild.id)
        if not values["enabled"] or message.channel.id not in values["channel_ids"]:
            return
        if not await core.module_enabled(self.bot, message.guild.id, "ai"):
            return

        features = await setup_v2_ui.get_ai_features(self.bot, message.guild.id)
        if not features["natural_enabled"]:
            return

        settings = await ai_service.get_settings(self.bot, message.guild.id)
        if not settings["enabled"] or not ai_service.is_channel_allowed(settings, message.channel.id):
            return
        role_ids = [role.id for role in getattr(message.author, "roles", ())]
        if not ai_service.is_role_allowed(settings, role_ids):
            return

        ai_cog = self.bot.get_cog("Ai")
        if ai_cog is None or not hasattr(ai_cog, "send_sentrix_reply"):
            return

        # Un utilisateur ne peut pas lancer deux réponses naturelles en parallèle.
        key = (message.guild.id, message.author.id)
        if key in self._busy:
            return
        self._busy.add(key)
        try:
            async with message.channel.typing():
                await ai_cog.send_sentrix_reply(
                    message.channel,
                    message.author,
                    content,
                    reply_to=message,
                )
        finally:
            self._busy.discard(key)


def _patch_setup() -> None:
    current_render = setup_ui.SetupView.render
    if not getattr(current_render, "_sentrix_ai_bare_v3", False):
        def render_ai_bare(self):
            current_render(self)
            if self.category != "ai":
                return
            button = discord.ui.Button(
                label="Parler sans mention",
                style=discord.ButtonStyle.secondary,
                row=1,
            )

            async def callback(interaction: discord.Interaction):
                values = await bare_settings(self.bot, self.guild.id)
                channels = [self.guild.get_channel(cid) for cid in values["channel_ids"]]
                channel_text = ", ".join(c.mention for c in channels if c) or "Aucun salon"
                panel = embeds.info(
                    f"**État :** {'ACTIF' if values['enabled'] else 'INACTIF'}\n"
                    f"**Salons :** {channel_text}\n\n"
                    "Dans ces salons, un membre peut écrire simplement `salut`, `ça va ?` ou une question normale. "
                    "SentriX ne répond jamais sans mention dans les autres salons.",
                    title="Conversation IA sans mention",
                )
                await interaction.response.send_message(
                    embed=panel,
                    view=BareChatManageView(self, interaction.user.id),
                    ephemeral=True,
                )

            button.callback = callback
            self.add_item(button)

        render_ai_bare._sentrix_ai_bare_v3 = True
        setup_ui.SetupView.render = render_ai_bare

    current_build = setup_ui.SetupView.build_embed
    if not getattr(current_build, "_sentrix_ai_bare_v3", False):
        async def build_ai_bare(self):
            panel = await current_build(self)
            if self.category == "ai":
                values = await bare_settings(self.bot, self.guild.id)
                channels = [self.guild.get_channel(cid) for cid in values["channel_ids"]]
                panel.add_field(
                    name="Conversation sans mention",
                    value=(
                        f"**État :** {'ACTIF' if values['enabled'] else 'INACTIF'}\n"
                        "**Salons :** "
                        + (", ".join(c.mention for c in channels if c) or "Aucun salon configuré")
                        + "\nÉcrire `salut` suffit uniquement dans ces salons."
                    ),
                    inline=False,
                )
            return panel

        build_ai_bare._sentrix_ai_bare_v3 = True
        setup_ui.SetupView.build_embed = build_ai_bare


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_ai_bare_v3_installed", False):
        return
    await ensure_schema(bot)
    runtime = BareNaturalRuntime(bot)
    bot.add_listener(runtime.on_message, "on_message")
    bot._sentrix_ai_bare_v3_runtime = runtime
    _patch_setup()
    bot._sentrix_ai_bare_v3_installed = True


__all__ = ["bare_settings", "set_bare_enabled", "set_bare_channels", "install"]
