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


def presentation_panel(url: str, *, banner: bool | None = None,
                       english: bool = False, bot: commands.Bot | None = None) -> panels.Panneau:
    from .presentation_feedback import FeedbackButton
    sections = (
        (panels.Section("Security & moderation", texte="Anti-spam, anti-raid, sanctions and staff tools."),
         panels.Section("Server management", texte="Tickets, logs, welcome, verification and automation."),
         panels.Section("Community", texte="Levels, economy, games, events, music and AI."))
        if english else
        (panels.Section("Sécurité et modération", texte="Anti-spam, anti-raid, sanctions et outils du staff."),
         panels.Section("Gestion du serveur", texte="Tickets, logs, bienvenue, vérification et automatisations."),
         panels.Section("Communauté", texte="Niveaux, économie, jeux, événements, musique et IA."))
    )
    view = panels.Panneau(
        titre="SentriX",
        sous_titre=("Secure and manage your Discord server." if english
                    else "Protégez et organisez votre serveur avec un seul bot."),
        kind="brand", banniere=banner, sections=sections,
        boutons=(panels.Bouton(libelle="Add SentriX" if english else "Ajouter SentriX", url=url),),
        pied=("Add SentriX, then run /setup." if english
              else "Ajoutez SentriX, puis lancez /setup."),
    )
    if bot is not None:
        container = next((item for item in view.children if isinstance(item, discord.ui.Container)), None)
        if container is not None:
            rows = [item for item in container.children if isinstance(item, discord.ui.ActionRow)]
            if rows and len(rows[-1].children) < 5:
                rows[-1].add_item(FeedbackButton(bot, english))
            else:
                container.add_item(discord.ui.ActionRow(FeedbackButton(bot, english)))
    return view


def _old_panel(message: discord.Message, bot_id: int) -> bool:
    if getattr(getattr(message, "author", None), "id", None) != bot_id:
        return False
    try:
        serialized = "\n".join(str(component.to_dict()) for component in message.components)
    except (TypeError, AttributeError):
        return False
    return (("Add SentriX" in serialized or "Ajouter SentriX" in serialized)
            and "/setup" in serialized)


@app_commands.guild_only()
@app_commands.describe(
    channel="Salon où publier la présentation.",
    banniere="Afficher ou masquer la bannière ultra-fine en haut du panneau.",
)
async def _publish(
    interaction: discord.Interaction,
    channel: discord.TextChannel | None = None,
    banniere: bool = True,
) -> None:
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message(
            "Cette commande s'utilise dans un serveur Discord.", ephemeral=True,
        )
        return
    # Le propriétaire du bot peut publier sans disposer de Gérer le serveur
    # (lui aussi reste soumis aux permissions d’écriture du salon cible).
    from database.db import PRIMARY_CREATOR_ID
    authorized = bool(getattr(getattr(interaction.user, "guild_permissions", None), "manage_guild", False))
    authorized = authorized or interaction.user.id == PRIMARY_CREATOR_ID
    if not authorized:
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

    from . import language_runtime
    english = (await language_runtime.get_language(interaction.client, guild.id)
               == language_runtime.LANG_EN)
    await interaction.response.defer(ephemeral=True, thinking=True)
    panel = presentation_panel(url, banner=banniere, english=english, bot=interaction.client)
    previous = None
    try:
        tracked = await interaction.client.db.fetchone(
            "SELECT message_id FROM sentrix_presentation_posts WHERE guild_id=? AND channel_id=?",
            (guild.id, destination.id),
        )
        if tracked:
            candidate = await destination.fetch_message(int(tracked["message_id"]))
            if candidate.author.id == interaction.client.user.id:
                previous = candidate
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        pass
    except Exception:
        logger.exception("Unable to fetch saved presentation")

    if previous is None and perms.read_message_history:
        try:
            async for candidate in destination.history(limit=75):
                if _old_panel(candidate, interaction.client.user.id):
                    previous = candidate
                    break
        except discord.HTTPException:
            pass

    updated = False
    try:
        if previous is not None:
            try:
                sent = await previous.edit(view=panel, attachments=panel.fichiers())
                updated = True
            except discord.HTTPException:
                logger.warning("Could not update prior presentation; posting a new one")
                sent = await panels.envoyer(destination, panel)
        else:
            sent = await panels.envoyer(destination, panel)
    except discord.HTTPException:
        logger.exception("Impossible de publier /presentation dans le salon %s", destination.id)
        await interaction.followup.send(
            "Échec de la publication. Vérifiez les permissions du bot dans ce salon.",
            ephemeral=True,
        )
        return

    try:
        await interaction.client.db.execute(
            "INSERT INTO sentrix_presentation_posts(guild_id,channel_id,message_id) VALUES(?,?,?) "
            "ON CONFLICT(guild_id,channel_id) DO UPDATE SET message_id=excluded.message_id",
            (guild.id, destination.id, sent.id),
        )
    except Exception:
        logger.exception("Could not persist presentation id")
    result = ("Presentation updated" if updated else "Presentation posted") if english else (
        "Présentation mise à jour" if updated else "Présentation publiée"
    )
    await interaction.followup.send(
        f"{result} : {destination.mention}.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
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
    from .presentation_feedback import ensure_schema, FeedbackPersistentView
    await ensure_schema(bot)
    bot.add_view(FeedbackPersistentView(bot))
    slash_catalog.register_native("presentation", _native_presentation)
