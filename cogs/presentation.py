"""Commande slash de présentation publique du bot SentriX.

Affiche un panneau Discord Components V2 unique et un bouton d'installation
natif. Aucune URL d'invitation n'est affichée dans le corps du message.
"""
from __future__ import annotations

import asyncio
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


def _presentation(invite_url: str, *, with_banner: bool = False,
                  english: bool = False, bot: commands.Bot | None = None) -> panels.Panneau:
    """Concise public panel, with a permanent Give feedback action."""
    from .presentation_feedback import FeedbackButton

    if english:
        sections = (
            panels.Section("Security & moderation", texte="Anti-spam, anti-raid, sanctions and staff tools."),
            panels.Section("Server management", texte="Tickets, logs, welcome, verification and automation."),
            panels.Section("Community", texte="Levels, economy, games, events, music and AI."),
        )
        subtitle = "Secure, manage and grow your Discord server."
        foot = "Add SentriX and run /setup to configure your server."
        add_label = "Add SentriX"
    else:
        sections = (
            panels.Section("Sécurité & modération", texte="Anti-spam, anti-raid, sanctions et outils du staff."),
            panels.Section("Gestion du serveur", texte="Tickets, logs, bienvenue, vérification et automatisations."),
            panels.Section("Communauté", texte="Niveaux, économie, jeux, événements, musique et IA."),
        )
        subtitle = "Protégez et organisez votre serveur avec un seul bot."
        foot = "Ajoutez SentriX et lancez /setup pour le configurer."
        add_label = "Ajouter SentriX"

    panel = panels.Panneau(
        titre="SentriX", sous_titre=subtitle, sections=sections,
        kind="brand", banniere=with_banner, pied=foot,
        boutons=(panels.Bouton(libelle=add_label, url=invite_url),),
    )
    if bot is not None:
        container = next((item for item in panel.children if isinstance(item, discord.ui.Container)), None)
        if container is not None:
            rows = [item for item in container.children if isinstance(item, discord.ui.ActionRow)]
            if rows and len(rows[-1].children) < 5:
                rows[-1].add_item(FeedbackButton(bot, english))
            else:
                container.add_item(discord.ui.ActionRow(FeedbackButton(bot, english)))
    return panel


def _is_old_presentation(message: discord.Message, bot_user_id: int) -> bool:
    """Match only older SentriX install panels, not unrelated bot messages."""
    if getattr(message.author, "id", None) != bot_user_id:
        return False
    try:
        data = "\n".join(str(component.to_dict()) for component in message.components)
    except (AttributeError, TypeError):
        return False
    return (
        ("Add SentriX" in data or "Ajouter SentriX" in data)
        and "/setup" in data
    )


class SentriXPresentation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.feedback_locks: dict[tuple[int, int], asyncio.Lock] = {}

    @app_commands.command(
        name="presentation",
        description="Publish or refresh the public SentriX presentation.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(salon="Channel to publish or refresh the presentation")
    async def presentation(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel | None = None,
    ) -> None:
        from . import language_runtime

        if interaction.guild is None:
            return await interaction.response.send_message(
                "This command requires a server.", ephemeral=True,
            )
        english = (
            await language_runtime.get_language(self.bot, interaction.guild.id)
            == language_runtime.LANG_EN
        )
        permissions = getattr(interaction.user, "guild_permissions", None)
        if not permissions or not permissions.manage_guild:
            return await interaction.response.send_message(
                "Manage Server permission required." if english
                else "Permission Gérer le serveur requise.",
                ephemeral=True,
            )
        target = salon or interaction.channel
        if not isinstance(target, discord.TextChannel):
            return await interaction.response.send_message(
                "Select a text channel." if english else "Choisissez un salon textuel.",
                ephemeral=True,
            )
        bot_member = interaction.guild.me
        if bot_member is None:
            return await interaction.response.send_message(
                "Cannot verify bot permissions." if english
                else "Impossible de vérifier les permissions de SentriX.",
                ephemeral=True,
            )
        bot_permissions = target.permissions_for(bot_member)
        if not (bot_permissions.view_channel and bot_permissions.send_messages):
            return await interaction.response.send_message(
                "SentriX cannot post in this channel." if english
                else "SentriX ne peut pas publier dans ce salon.",
                ephemeral=True,
            )
        invite_url = _invite_url(self.bot)
        if not invite_url:
            return await interaction.response.send_message(
                "Install link unavailable." if english
                else "Le lien d'installation est indisponible.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True, thinking=True)
        panel = _presentation(invite_url, english=english, bot=self.bot)
        existing = None
        try:
            tracked = await self.bot.db.fetchone(
                "SELECT message_id FROM sentrix_presentation_posts "
                "WHERE guild_id=? AND channel_id=?",
                (interaction.guild.id, target.id),
            )
            if tracked:
                message = await target.fetch_message(int(tracked["message_id"]))
                if message.author.id == self.bot.user.id:
                    existing = message
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
        except Exception:
            logger.exception("Presentation lookup failed")

        # Try to update an older presentation already posted by SentriX.
        if existing is None and bot_permissions.read_message_history:
            try:
                async for message in target.history(limit=75):
                    if _is_old_presentation(message, self.bot.user.id):
                        existing = message
                        break
            except (discord.Forbidden, discord.HTTPException):
                pass

        updated = False
        if existing is not None:
            try:
                await existing.edit(view=panel, attachments=[])
                updated = True
                sent = existing
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("Could not refresh previous presentation")
        if not updated:
            try:
                sent = await panels.envoyer(target, panel)
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Presentation publishing failed in channel %s", target.id)
                return await interaction.followup.send(
                    "The presentation could not be published." if english
                    else "La présentation n'a pas pu être publiée.",
                    ephemeral=True,
                )
        try:
            await self.bot.db.execute(
                "INSERT INTO sentrix_presentation_posts (guild_id,channel_id,message_id) "
                "VALUES (?,?,?) ON CONFLICT(guild_id,channel_id) "
                "DO UPDATE SET message_id=excluded.message_id",
                (interaction.guild.id, target.id, sent.id),
            )
        except Exception:
            logger.exception("Failed to persist presentation message ID")
        outcome = (
            "Presentation updated" if updated else "Presentation posted"
        ) if english else (
            "Présentation mise à jour" if updated else "Présentation publiée"
        )
        await interaction.followup.send(
            f"{outcome} : {target.mention}.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    from .presentation_feedback import FeedbackPersistentView, ensure_schema

    await ensure_schema(bot)
    bot.add_view(FeedbackPersistentView(bot))
    await bot.add_cog(SentriXPresentation(bot))
