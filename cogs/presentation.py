"""Commande slash de présentation publique du bot SentriX.

Affiche un panneau Discord Components V2 unique et un bouton d'installation
natif. Aucune URL d'invitation n'est affichée dans le corps du message.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import sentrix_panels as panels

logger = logging.getLogger("bot.presentation")


def _invite_url(bot: commands.Bot) -> str | None:
    """Construit l'URL OAuth2 depuis l'application connectée, jamais un ID codé en dur."""
    application_id = bot.application_id or getattr(bot.user, "id", None)
    if not application_id:
        return None
    # Permissions fonctionnelles explicites ; ne demande pas Administrator.
    permissions = discord.Permissions(
        view_channel=True,
        send_messages=True,
        send_messages_in_threads=True,
        read_message_history=True,
        embed_links=True,
        attach_files=True,
        add_reactions=True,
        manage_messages=True,
        manage_channels=True,
        manage_roles=True,
        moderate_members=True,
        kick_members=True,
        ban_members=True,
        manage_webhooks=True,
        connect=True,
        speak=True,
    )
    return discord.utils.oauth_url(
        int(application_id),
        permissions=permissions,
        scopes=("bot", "applications.commands"),
    )


def _presentation(invite_url: str, *, with_banner: bool = True) -> panels.Panneau:
    return panels.Panneau(
        titre="SentriX",
        sous_titre="Un seul bot pour protéger, organiser et animer votre serveur Discord.",
        kind="brand",
        banniere=with_banner,
        sections=(
            panels.Section(
                "Sécurité et modération",
                texte="**Protection** contre le spam, les liens suspects et les raids. "
                      "**Sanctions**, permissions et outils pour le staff.",
            ),
            panels.Section(
                "Organisation du serveur",
                texte="**Tickets**, journaux détaillés, accueil des membres, "
                      "vérification et automatisations.",
            ),
            panels.Section(
                "Communauté",
                texte="**Niveaux**, économie, jeux, événements, musique "
                      "et outils d'intelligence artificielle.",
            ),
            panels.Section(
                "Pour commencer",
                texte="Ajoutez SentriX à votre serveur avec le bouton ci-dessous, "
                      "puis utilisez `/setup` pour le configurer.",
            ),
        ),
        pied="SentriX • Installation et configuration guidées",
        boutons=(panels.Bouton(libelle="Ajouter SentriX", url=invite_url),),
    )


class SentriXPresentation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="presentation",
        description="Post a SentriX introduction with an Add SentriX button.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(salon="Text channel to post in (current channel by default)")
    async def presentation(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Cette commande fonctionne uniquement dans un serveur.", ephemeral=True,
            )
            return

        member_permissions = getattr(interaction.user, "guild_permissions", None)
        if not member_permissions or not member_permissions.manage_guild:
            await interaction.response.send_message(
                "Vous devez avoir la permission **Gérer le serveur**.",
                ephemeral=True,
            )
            return

        target = salon or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message(
                "Choisissez un salon textuel avec l'option `salon`.",
                ephemeral=True,
            )
            return

        bot_member = interaction.guild.me
        if bot_member is None:
            await interaction.response.send_message(
                "Impossible de vérifier mes permissions dans ce serveur.",
                ephemeral=True,
            )
            return

        bot_permissions = target.permissions_for(bot_member)
        if not (bot_permissions.view_channel and bot_permissions.send_messages):
            await interaction.response.send_message(
                "Je n'ai pas la permission d'envoyer des messages dans ce salon.",
                ephemeral=True,
            )
            return

        invite_url = _invite_url(self.bot)
        if not invite_url:
            await interaction.response.send_message(
                "L'invitation SentriX est momentanément indisponible.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        panneau = _presentation(invite_url, with_banner=bot_permissions.attach_files)
        try:
            await panels.envoyer(target, panneau)
        except discord.Forbidden:
            await interaction.followup.send(
                "Publication refusée : vérifiez les permissions de SentriX dans ce salon.",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            logger.exception("Échec de la publication de /presentation dans %s.", target.id)
            await interaction.followup.send(
                "La présentation n'a pas pu être publiée. Réessayez.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"Présentation SentriX publiée dans {target.mention}.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SentriXPresentation(bot))
