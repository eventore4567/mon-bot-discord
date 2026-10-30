"""SentriX /presentation (slash uniquement), publié par le catalogue canonique.

Utilise le panneau Components V2 du bot et un bouton d'installation Discord.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import sentrix_panels as panels

logger = logging.getLogger("bot.presentation")


def invite_url(bot: commands.Bot) -> str | None:
    application_id = getattr(bot, "application_id", None) or getattr(getattr(bot, "user", None), "id", None)
    if not application_id:
        return None

    # Permissions ciblées, jamais Administrator.
    permissions = discord.Permissions(
        view_channel=True,
        send_messages=True,
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


def presentation_panel(url: str, *, banner: bool | None = None) -> panels.Panneau:
    return panels.Panneau(
        titre="SentriX",
        sous_titre="Protégez, organisez et animez votre serveur avec un seul bot.",
        kind="brand",
        banniere=banner,
        sections=(
            panels.Section(
                "Sécurité et modération",
                texte="Protection anti-spam, anti-raid et anti-liens. "
                      "Sanctions, permissions et outils de gestion du staff.",
            ),
            panels.Section(
                "Gestion du serveur",
                texte="Tickets interactifs, logs détaillés, accueil des membres, "
                      "vérification et automatisations.",
            ),
            panels.Section(
                "Communauté",
                texte="Niveaux, économie, mini-jeux, événements, musique et assistant IA.",
            ),
            panels.Section(
                "Installation",
                texte="Appuyez sur **Ajouter SentriX**, choisissez votre serveur, "
                      "puis lancez /setup pour le configurer.",
            ),
        ),
        boutons=(panels.Bouton(libelle="Ajouter SentriX", url=url),),
        pied="SentriX • Votre serveur, votre configuration",
    )


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(channel="Text channel where SentriX should publish the presentation.")
async def _publish(interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message(
            "Cette commande s'utilise dans un serveur Discord.", ephemeral=True,
        )
        return
    if not getattr(getattr(interaction.user, "guild_permissions", None), "manage_guild", False):
        await interaction.response.send_message(
            "Il faut la permission **Gérer le serveur** pour publier cette présentation.",
            ephemeral=True,
        )
        return

    destination = channel or interaction.channel
    if not isinstance(destination, discord.TextChannel):
        await interaction.response.send_message(
            "Sélectionnez un salon textuel avec l'option channel.", ephemeral=True,
        )
        return

    bot_member = guild.me
    if bot_member is None:
        await interaction.response.send_message(
            "Impossible de vérifier mes permissions dans ce serveur.", ephemeral=True,
        )
        return

    perms = destination.permissions_for(bot_member)
    if not (perms.view_channel and perms.send_messages):
        await interaction.response.send_message(
            "Je n'ai pas accès à ce salon ou je ne peux pas y écrire.", ephemeral=True,
        )
        return

    url = invite_url(interaction.client)
    if not url:
        await interaction.response.send_message(
            "L'invitation SentriX est indisponible actuellement.", ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        await panels.envoyer(
            destination,
            presentation_panel(url, banner=None if perms.attach_files else False),
        )
    except discord.HTTPException:
        logger.exception("Impossible de publier /presentation dans le salon %s", destination.id)
        await interaction.followup.send(
            "Échec de la publication. Vérifiez les permissions du bot dans ce salon.",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"Présentation publiée dans {destination.mention}.",
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


# Le catalogue reconstruit tout l'arbre slash au sync : commande native et
# sans préfixe, enregistrée ici avant la publication du catalogue.
def _native_presentation(_bot: commands.Bot) -> app_commands.Command:
    return app_commands.Command(
        name="presentation",
        description="Post a SentriX presentation and invite button in a channel.",
        callback=_publish,
    )


async def setup(bot: commands.Bot) -> None:
    from utils import slash_catalog
    slash_catalog.register_native("presentation", _native_presentation)
