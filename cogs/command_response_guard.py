"""Filet de sécurité : aucune commande SentriX valide ne doit finir silencieusement.

Les commandes gardent leur réponse normale. Cette couche intervient uniquement lorsqu'une
commande s'est terminée avec succès sans avoir envoyé de réponse via Context.send/reply.
Pour les commandes slash, elle répond seulement si l'interaction n'a encore reçu aucune
réponse. Les erreurs restent gérées par les handlers globaux de main.py.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from utils import embeds

logger = logging.getLogger("bot.command-response-guard")
_INSTALLED = False


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # reply_reference_fix et le moteur visuel sont déjà installés lorsque cette couche
    # s'exécute. On enveloppe donc la version FINALE de Context.send pour enregistrer toute
    # réponse normale sans modifier son rendu, ses embeds ni ses permissions.
    current_send = commands.Context.send
    if not getattr(current_send, "_sentrix_response_marker", False):
        async def send_with_response_marker(self: commands.Context, *args, **kwargs):
            self._sentrix_response_sent = True
            return await current_send(self, *args, **kwargs)

        send_with_response_marker._sentrix_response_marker = True
        commands.Context.send = send_with_response_marker

    async def ensure_prefix_command_response(ctx: commands.Context) -> None:
        # Les slash/hybrid slash utilisent l'événement app_command_completion ci-dessous.
        if getattr(ctx, "interaction", None) is not None:
            return
        if getattr(ctx, "_sentrix_response_sent", False):
            return
        try:
            await ctx.send(
                embed=embeds.success(
                    "La commande s'est terminée correctement.",
                    title="✅ Commande exécutée",
                )
            )
            logger.info(
                "Réponse de secours envoyée pour +%s (user=%s, guild=%s).",
                getattr(getattr(ctx, "command", None), "qualified_name", "inconnue"),
                getattr(getattr(ctx, "author", None), "id", None),
                getattr(getattr(ctx, "guild", None), "id", None),
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Impossible d'envoyer la réponse de secours pour %s.",
                getattr(getattr(ctx, "command", None), "qualified_name", "commande inconnue"),
                exc_info=True,
            )

    async def ensure_slash_command_response(
        interaction: discord.Interaction,
        command: discord.app_commands.Command | discord.app_commands.ContextMenu,
    ) -> None:
        try:
            if interaction.response.is_done():
                return
            await interaction.response.send_message(
                embed=embeds.success(
                    "La commande s'est terminée correctement.",
                    title="✅ Commande exécutée",
                ),
                ephemeral=True,
            )
            logger.info(
                "Réponse slash de secours envoyée pour /%s (user=%s, guild=%s).",
                getattr(command, "qualified_name", getattr(command, "name", "inconnue")),
                getattr(interaction.user, "id", None),
                interaction.guild_id,
            )
        except discord.InteractionResponded:
            return
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Impossible d'envoyer la réponse slash de secours pour %s.",
                getattr(command, "name", "commande inconnue"),
                exc_info=True,
            )

    bot.add_listener(ensure_prefix_command_response, "on_command_completion")
    bot.add_listener(ensure_slash_command_response, "on_app_command_completion")
    _INSTALLED = True
    logger.info("Garantie de réponse pour les commandes préfixées et slash activée.")
