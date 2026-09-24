"""Accueil minimal envoyé lorsque SentriX rejoint un serveur.

Aucun gros panneau n'est publié dans un salon. Le propriétaire reçoit seulement un
court message privé avec +help, +setup et le lien du dashboard.
"""
from __future__ import annotations

import logging
import os

import discord
from discord.ext import commands

import config
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.guild-arrival")

WELCOME_COLOUR = 0x6C5CE7
OFFICIAL_SUPPORT_URL = "https://discord.gg/5P5Bqjqu5t"
SUPPORT_URL = (os.getenv("SUPPORT_SERVER_URL") or OFFICIAL_SUPPORT_URL).strip()


def _safe_url(value: str | None) -> str | None:
    value = str(value or "").strip()
    return value if value.startswith(("https://", "http://")) else None


def _dashboard_url() -> str | None:
    return (
        _safe_url(getattr(config, "DASHBOARD_SHARE_URL", None))
        or _safe_url(getattr(config, "DASHBOARD_APP_URL", None))
    )


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
    invite = _invite_url(bot)
    dashboard = _dashboard_url()
    support = _safe_url(SUPPORT_URL) or OFFICIAL_SUPPORT_URL

    links = [f"[Serveur officiel]({support})"]
    if dashboard:
        links.append(f"[Dashboard]({dashboard})")
    if invite:
        links.append(f"[Inviter SentriX]({invite})")

    embed = discord.Embed(
        title="SentriX • Installation réussie",
        description=(
            f"{owner}, **SentriX est maintenant actif sur {guild.name}.**\nVous pouvez configurer l'essentiel en quelques minutes depuis le centre de contrôle."
        ),
        colour=discord.Colour(WELCOME_COLOUR),
    )
    embed.add_field(
        name="Démarrage rapide",
        value=(
            "**`+setup`** — ouvre toute la configuration du serveur\n"
            "**`+help`** — affiche les commandes et leur utilisation\n"
            "**`SentriX ...`** — parle naturellement avec l'IA"
        ),
        inline=False,
    )
    embed.add_field(
        name="Ce que SentriX peut gérer",
        value=(
            "Modération • sécurité • AutoMod • tickets • logs • rôles • niveaux • "
            "bienvenue/départs • automatisations • communauté"
        ),
        inline=False,
    )
    embed.add_field(
        name="Avant de commencer",
        value=(
            "Placez le rôle **SentriX** au-dessus des rôles qu'il doit gérer, puis utilisez le bouton **Configurer** ci-dessous.\n"
            "Tout est **inactif tant que vous ne l'avez pas configuré** : rien ne se déclenche sans votre accord.\n"
            "Besoin d'un coup de main ? **Demander de l'aide** crée une invitation temporaire (24 h, un seul usage) pour le créateur de SentriX."
        ),
        inline=False,
    )
    embed.add_field(
        name="Liens officiels",
        value=" • ".join(links),
        inline=False,
    )

    bot_user = getattr(bot, "user", None)
    avatar = getattr(getattr(bot_user, "display_avatar", None), "url", None)
    if avatar:
        embed.set_author(name="SentriX • Nouveau serveur", icon_url=str(avatar))
        embed.set_thumbnail(url=str(avatar))
    else:
        embed.set_author(name="SentriX • Nouveau serveur")
    embed.set_footer(text="SentriX • Configuration rapide • Support officiel disponible ci-dessous")
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

        support = _safe_url(SUPPORT_URL) or OFFICIAL_SUPPORT_URL
        self.add_item(
            discord.ui.Button(
                label="Serveur officiel",
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
                'Le centre de configuration est momentanément indisponible. Utilisez `+setup`.',
                ephemeral=True,
            )

        active = getattr(configuration, "active_by_guild", {}).get(interaction.guild_id)
        if active and active[1] != member.id:
            return await interaction.response.send_message(
                f"Une configuration est déjà ouverte par <@{active[1]}>",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        try:
            await configuration._open_setup_panel(interaction.channel, author=member)
        except Exception:
            logger.exception("Ouverture du setup depuis le message d'arrivée impossible.")
            return await interaction.followup.send(
                "Je n'ai pas pu ouvrir le panneau ici. Vérifiez mes permissions puis utilisez `+setup`.",
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

    @discord.ui.button(
        label="Demander de l'aide",
        style=discord.ButtonStyle.secondary,
        custom_id="sentrix:setup-help:request:v1",
        row=1,
    )
    async def request_help(self, interaction: discord.Interaction, _button: discord.ui.Button):
        """Même action que l'ancienne carte séparée : invitation temporaire pour le créateur."""
        from .owner_log_rebuild import request_setup_help

        await request_setup_help(self.bot, interaction)


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

        dashboard = _dashboard_url()

        owner = guild.owner
        if owner is None:
            try:
                owner = await self.bot.fetch_user(int(guild.owner_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError):
                owner = None
        if owner is None:
            logger.info("Accueil MP ignoré : propriétaire introuvable guild=%s", guild.id)
            return

        embed = discord.Embed(
            title="SentriX est prêt",
            description=f"SentriX a été ajouté à **{guild.name}**.",
            colour=discord.Colour(WELCOME_COLOUR),
        )
        embed.add_field(
            name="Démarrage",
            value=(
                "`+setup` — configurer le serveur\n"
                "`+help` — voir les commandes réellement disponibles"
            ),
            inline=False,
        )
        bot_user = getattr(self.bot, "user", None)
        avatar = getattr(getattr(bot_user, "display_avatar", None), "url", None)
        if avatar:
            embed.set_thumbnail(url=str(avatar))
        embed.set_footer(text=f"SentriX • {guild.name}")

        view = discord.ui.View(timeout=None)
        if dashboard:
            view.add_item(discord.ui.Button(
                label="Ouvrir le Dashboard",
                style=discord.ButtonStyle.link,
                url=dashboard,
            ))
        support = _safe_url(SUPPORT_URL) or OFFICIAL_SUPPORT_URL
        view.add_item(discord.ui.Button(
            label="Serveur officiel",
            style=discord.ButtonStyle.link,
            url=support,
        ))

        try:
            await owner.send(
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            logger.info("Accueil MP SentriX envoyé au propriétaire de %s.", guild.id)
        except (discord.Forbidden, discord.HTTPException):
            logger.info("Accueil MP impossible pour le propriétaire de %s.", guild.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildArrival(bot))
    bot.add_view(GuildArrivalView(bot))

    if bot.get_cog("OwnerLogRebuild") is None:
        from .owner_log_rebuild import OwnerLogRebuild
        await bot.add_cog(OwnerLogRebuild(bot))

    # V85/V86 supprimés : le routage vient de log_config et la validation des permissions
    # est faite par log_service.validate_channel avant chaque envoi.
