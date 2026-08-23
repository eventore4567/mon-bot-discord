"""Accueil unique et complet envoyé automatiquement lorsque SentriX rejoint un serveur."""
from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord.ext import commands

import config

logger = logging.getLogger("bot.guild-arrival")

WELCOME_COLOUR = 0x6D5DF5
SUPPORT_URL = (os.getenv("SUPPORT_SERVER_URL") or "").strip()
LEGACY_WELCOME_TITLE = "Bienvenue sur SentriX V3"
LEGACY_WELCOME_MARKER = "Pour les membres"


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
        title="Bienvenue sur SentriX",
        description=(
            f"{owner}, **SentriX est maintenant actif sur {guild.name}.**\n\n"
            "## Configuration du serveur\n"
            "**`+setup`** ouvre le centre de configuration complet : **rôles, salons, permissions, "
            "sécurité, AutoMod, tickets, niveaux, bienvenue, départs, logs et automatisations**.\n"
            "**`+help`** affiche toutes les commandes disponibles et explique leur utilisation.\n\n"
            "## Pour les membres\n"
            "**`+profile`** affiche le profil communautaire, la saison, le streak, les missions et les succès.\n"
            "**IA SentriX** : écris simplement `SentriX ...` ou utilise **`+ai`** pour parler au bot.\n\n"
            "## À vérifier avant de commencer\n"
            "Place le rôle **SentriX** au-dessus des rôles qu'il doit gérer. Cela permet aux fonctions de "
            "modération, rôles, tickets et sécurité de fonctionner correctement.\n\n"
            "## Choisis la langue\n"
            "Utilise **Français** ou **English** ci-dessous. Tu pourras ensuite la modifier depuis la configuration."
        ),
        colour=discord.Colour(WELCOME_COLOUR),
    )
    bot_user = getattr(bot, "user", None)
    avatar = getattr(getattr(bot_user, "display_avatar", None), "url", None)
    if avatar:
        embed.set_author(name="SentriX • Démarrage", icon_url=str(avatar))
    else:
        embed.set_author(name="SentriX • Démarrage")
    embed.set_footer(text="SentriX • Configure tout depuis les boutons ci-dessous")
    return embed


class GuildArrivalView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

        dashboard = _safe_url(getattr(config, "DASHBOARD_APP_URL", None))
        if dashboard:
            self.add_item(
                discord.ui.Button(
                    label="Dashboard",
                    style=discord.ButtonStyle.link,
                    url=dashboard,
                    row=0,
                )
            )

        invite = _invite_url(bot)
        if invite:
            self.add_item(
                discord.ui.Button(
                    label="Inviter SentriX",
                    style=discord.ButtonStyle.link,
                    url=invite,
                    row=0,
                )
            )

        support = _safe_url(SUPPORT_URL)
        if support:
            self.add_item(
                discord.ui.Button(
                    label="Support",
                    style=discord.ButtonStyle.link,
                    url=support,
                    row=0,
                )
            )

    @discord.ui.button(
        label="Configurer",
        style=discord.ButtonStyle.primary,
        custom_id="sentrix:guild-arrival:setup:v3",
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

    async def _choose_language(self, interaction: discord.Interaction, language: str) -> None:
        if interaction.guild_id is None:
            return await interaction.response.send_message(
                "Le choix de langue doit être effectué dans un serveur.",
                ephemeral=True,
            )

        try:
            from . import language_runtime

            await language_runtime.set_language(self.bot, interaction.guild_id, language)
        except Exception:
            logger.exception("Impossible de changer la langue depuis l'accueil guild=%s", interaction.guild_id)
            return await interaction.response.send_message(
                "La langue n'a pas pu être enregistrée pour le moment.",
                ephemeral=True,
            )

        if language == "en":
            text = "Language set to **English**. SentriX interfaces will now use English where available."
        else:
            text = "Langue définie sur **Français**. Les interfaces SentriX utiliseront maintenant le français."
        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(
        label="Français",
        emoji="🇫🇷",
        style=discord.ButtonStyle.secondary,
        custom_id="sentrix:guild-arrival:language:fr:v3",
        row=1,
    )
    async def language_fr(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._choose_language(interaction, "fr")

    @discord.ui.button(
        label="English",
        emoji="🇬🇧",
        style=discord.ButtonStyle.secondary,
        custom_id="sentrix:guild-arrival:language:en:v3",
        row=1,
    )
    async def language_en(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._choose_language(interaction, "en")


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

    def _is_legacy_welcome(self, message: discord.Message, keep_message_id: int) -> bool:
        bot_user = self.bot.user
        if bot_user is None or message.id == keep_message_id or message.author.id != bot_user.id:
            return False

        parts = [str(message.content or "")]
        for embed in message.embeds:
            parts.extend((str(embed.title or ""), str(embed.description or "")))
            if embed.author and embed.author.name:
                parts.append(str(embed.author.name))
            if embed.footer and embed.footer.text:
                parts.append(str(embed.footer.text))
            for field in embed.fields:
                parts.extend((str(field.name or ""), str(field.value or "")))
        blob = "\n".join(parts)
        return LEGACY_WELCOME_TITLE in blob and LEGACY_WELCOME_MARKER in blob

    async def _cleanup_legacy_welcome(self, channel: discord.TextChannel, keep_message_id: int) -> None:
        """Supprime uniquement l'ancien accueil V3 si un vieux listener l'envoie encore."""
        for delay in (1.0, 2.0, 4.0):
            await asyncio.sleep(delay)
            try:
                async for message in channel.history(limit=15):
                    if not self._is_legacy_welcome(message, keep_message_id):
                        continue
                    try:
                        await message.delete()
                        logger.info("Ancien accueil SentriX V3 supprimé dans guild=%s", channel.guild.id)
                    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                        pass
            except (discord.Forbidden, discord.HTTPException):
                return

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
                message = await channel.send(embed=embed, view=view, allowed_mentions=allowed_mentions)
                logger.info("Accueil unique SentriX envoyé dans %s (%s).", guild.name, guild.id)
                asyncio.create_task(
                    self._cleanup_legacy_welcome(channel, message.id),
                    name=f"sentrix-welcome-cleanup-{guild.id}",
                )
                return
            if guild.owner is not None:
                await guild.owner.send(embed=embed, view=view, allowed_mentions=allowed_mentions)
                logger.info("Accueil unique SentriX envoyé en MP au propriétaire de %s.", guild.id)
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Impossible d'envoyer l'accueil sur %s (%s).", guild.name, guild.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildArrival(bot))
    bot.add_view(GuildArrivalView(bot))
