"""Corrige la fermeture du panneau /setup sans délai d'interaction Discord."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from utils import embeds

logger = logging.getLogger("bot.setup-close-fix")
_INSTALLED = False


async def _send_ephemeral(interaction: discord.Interaction, text: str) -> None:
    """Envoie un retour privé, que l'interaction soit déjà acquittée ou non."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except discord.HTTPException:
        pass


def install(bot: commands.Bot) -> None:
    """Intercepte uniquement l'action `cancel` des boutons persistants de /setup."""
    del bot
    global _INSTALLED
    if _INSTALLED:
        return

    from . import configuration

    original_callback = configuration.SetupNavButton.callback

    async def setup_nav_callback(self, interaction: discord.Interaction):
        if self.action != "cancel":
            return await original_callback(self, interaction)

        # Discord exige un accusé de réception en moins de trois secondes. Il doit être
        # envoyé avant les lectures/écritures en base et avant la modification du message.
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        cog = interaction.client.get_cog("Configuration")
        if cog is None:
            return await _send_ephemeral(
                interaction,
                "Le module de configuration n'est pas chargé. Relancez `+setup`.",
            )

        view = cog.active_setups.get(self.message_id)
        session = None
        if view is not None:
            guild_id = int(view.guild_id)
            author_id = int(view.author_id)
        else:
            try:
                session = await cog.bot.db.get_setup_session(self.message_id)
            except Exception:
                logger.exception("Impossible de lire la session /setup %s.", self.message_id)
                session = None

            if not session:
                return await _send_ephemeral(
                    interaction,
                    "Cette session de configuration a expiré ou est déjà fermée.",
                )
            guild_id = int(session["guild_id"])
            author_id = int(session["author_id"])

        if interaction.guild is None or interaction.guild.id != guild_id:
            return await _send_ephemeral(
                interaction,
                "Cette configuration n'appartient pas à ce serveur.",
            )

        user = interaction.user
        authorized = user.id == author_id
        if isinstance(user, discord.Member):
            authorized = authorized or user.guild_permissions.administrator
        try:
            authorized = authorized or await cog.bot.is_owner(user)
        except Exception:
            pass
        if not authorized:
            try:
                authorized = await cog.bot.db.is_bot_manager(guild_id, user.id)
            except Exception:
                authorized = False

        if not authorized:
            return await _send_ephemeral(
                interaction,
                "Vous n'êtes pas autorisé à fermer cette configuration.",
            )

        # Nettoyage de la session avant l'édition du message pour qu'un ancien bouton ne
        # puisse jamais rouvrir ou verrouiller le panneau après sa fermeture.
        try:
            await cog.bot.db.delete_setup_session(self.message_id)
        except Exception:
            logger.exception("Impossible de supprimer la session /setup %s.", self.message_id)

        cog.active_setups.pop(self.message_id, None)
        cog.release_lock(guild_id, self.message_id)
        if view is not None:
            view.stop()

        try:
            await cog.bot.db.log_setup_history(
                guild_id,
                user.id,
                "Configuration",
                "panneau fermé",
            )
        except Exception:
            pass

        closed_embed = embeds.neutral(
            "Configuration fermée",
            "Le panneau a été fermé proprement. Relancez `+setup` pour le rouvrir.",
            color=configuration.SETUP_COLOR_MAIN,
        )
        try:
            if interaction.message is not None:
                await interaction.message.edit(embed=closed_embed, view=None)
        except discord.HTTPException:
            logger.warning("Le message /setup %s n'a pas pu être modifié.", self.message_id)

        await _send_ephemeral(interaction, "Configuration fermée.")
        logger.info(
            "Panneau /setup %s fermé par %s sur le serveur %s.",
            self.message_id,
            user.id,
            guild_id,
        )

    configuration.SetupNavButton.callback = setup_nav_callback
    _INSTALLED = True
    logger.info("Correctif de fermeture immédiate du panneau /setup chargé.")
