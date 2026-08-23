"""Accueil compact envoyé automatiquement lorsque SentriX rejoint un serveur."""
from __future__ import annotations

import logging
import os

import discord
from discord.ext import commands

import config

logger = logging.getLogger("bot.guild-arrival")

WELCOME_COLOUR = 0x6D5DF5
SUPPORT_URL = (os.getenv("SUPPORT_SERVER_URL") or "").strip()


def _safe_url(value: str | None) -> str | None:
    value = str(value or "").strip()
    return value if value.startswith(("https://", "http://")) else None


def _invite_url(bot: commands.Bot) -> str | None:
    user = getattr(bot, "user", None)
    if user is None:
        return None
    permissions = discord.Permissions(
        view_audit_log=True,
        manage_guild=True,
        manage_roles=True,
        manage_channels=True,
        kick_members=True,
        ban_members=True,
        moderate_members=True,
        manage_messages=True,
        embed_links=True,
        attach_files=True,
        read_message_history=True,
        add_reactions=True,
        connect=True,
        speak=True,
    )
    return discord.utils.oauth_url(
        user.id,
        permissions=permissions,
        scopes=("bot", "applications.commands"),
    )


def _arrival_embed(bot: commands.Bot, guild: discord.Guild) -> discord.Embed:
    owner = guild.owner.mention if guild.owner else f"<@{guild.owner_id}>"
    embed = discord.Embed(
        title="SentriX est prêt",
        description=(
            f"{owner}, SentriX est maintenant actif sur **{guild.name}** — utilise **`+setup`** "
            "pour le configurer et **`+help`** pour découvrir les commandes. Place simplement "
            "mon rôle au-dessus des rôles que je dois gérer."
        ),
        colour=discord.Colour(WELCOME_COLOUR),
    )
    bot_user = getattr(bot, "user", None)
    avatar = getattr(getattr(bot_user, "display_avatar", None), "url", None)
    if avatar:
        embed.set_author(name="SentriX", icon_url=str(avatar))
    else:
        embed.set_author(name="SentriX")
    embed.set_footer(text="SentriX • Configuration rapide")
    return embed


class GuildArrivalView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

        dashboard = _safe_url(getattr(config, "DASHBOARD_APP_URL", None))
        if dashboard:
            self.add_item(discord.ui.Button(
                label="Dashboard",
                style=discord.ButtonStyle.link,
                url=dashboard,
                row=0,
            ))
        support = _safe_url(SUPPORT_URL)
        if support:
            self.add_item(discord.ui.Button(
                label="Support",
                style=discord.ButtonStyle.link,
                url=support,
                row=0,
            ))
        invite = _invite_url(bot)
        if invite:
            self.add_item(discord.ui.Button(
                label="Inviter SentriX",
                style=discord.ButtonStyle.link,
                url=invite,
                row=0,
            ))

    @discord.ui.button(
        label="Configurer",
        style=discord.ButtonStyle.primary,
        custom_id="sentrix:guild-arrival:setup:v2",
        row=0,
    )
    async def configure(self, interaction: discord.Interaction, _button: discord.ui.Button):
        member = interaction.user
        permissions = getattr(member, "guild_permissions", None)
        allowed = bool(permissions and (permissions.administrator or permissions.manage_guild))
        if not allowed:
            return await interaction.response.send_message(
                "Seuls les administrateurs peuvent configurer SentriX.",
                ephemeral=True,
            )

        configuration = self.bot.get_cog("Configuration")
        if configuration is None or not hasattr(configuration, "_open_setup_panel"):
            return await interaction.response.send_message(
                "Le centre de configuration est momentanément indisponible. Utilise `+setup`.",
                ephemeral=True,
            )

        active = getattr(configuration, "active_by_guild", {}).get(interaction.guild_id)
        if active and active[1] != member.id:
            return await interaction.response.send_message(
                f"Une configuration est déjà ouverte par <@{active[1]}>.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        try:
            await configuration._open_setup_panel(interaction.channel, author=member)
        except Exception:
            logger.exception("Ouverture du setup depuis le message d'arrivée impossible.")
            return await interaction.followup.send(
                "Je n'ai pas pu ouvrir le panneau ici. Vérifie mes permissions puis utilise `+setup`.",
                ephemeral=True,
            )
        await interaction.followup.send(
            "Le centre de configuration est ouvert dans ce salon.",
            ephemeral=True,
        )


class GuildArrival(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _target_channel(guild: discord.Guild) -> discord.TextChannel | None:
        bot_member = guild.me
        if bot_member is None:
            return None
        ordered = [
            guild.system_channel,
            guild.public_updates_channel,
            guild.rules_channel,
            *guild.text_channels,
        ]
        seen: set[int] = set()
        for channel in ordered:
            if channel is None or channel.id in seen:
                continue
            seen.add(channel.id)
            permissions = channel.permissions_for(bot_member)
            if permissions.view_channel and permissions.send_messages and permissions.embed_links:
                return channel
        return None

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        try:
            await self.bot.db.ensure_guild(guild.id)
        except Exception:
            logger.exception("Initialisation de la base impossible pour le serveur %s.", guild.id)

        embed = _arrival_embed(self.bot, guild)
        view = GuildArrivalView(self.bot)
        channel = self._target_channel(guild)
        allowed_mentions = discord.AllowedMentions(users=True, roles=False, everyone=False)
        try:
            if channel is not None:
                await channel.send(embed=embed, view=view, allowed_mentions=allowed_mentions)
                logger.info("Accueil compact SentriX envoyé dans %s (%s).", guild.name, guild.id)
                return
            if guild.owner is not None:
                await guild.owner.send(embed=embed, view=view, allowed_mentions=allowed_mentions)
                logger.info("Accueil compact SentriX envoyé en MP au propriétaire de %s.", guild.id)
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Impossible d'envoyer l'accueil sur %s (%s).", guild.name, guild.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildArrival(bot))
    bot.add_view(GuildArrivalView(bot))
