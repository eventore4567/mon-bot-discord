"""Installation non destructive de l'identité visuelle globale SentriX."""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from utils import premium_style

logger = logging.getLogger("bot.premium-style")
_INSTALLED = False
_ORIGINALS: dict[str, Any] = {}


def _bot_user_from_context(ctx: commands.Context):
    return getattr(getattr(ctx, "bot", None), "user", None)


def _guild_from_messageable(messageable: Any):
    return getattr(messageable, "guild", None)


def _patch_context_send() -> None:
    original = commands.Context.send
    _ORIGINALS["context_send"] = original

    async def send(self: commands.Context, *args, **kwargs):
        args, kwargs = premium_style.style_kwargs(
            args,
            kwargs,
            command=self.command,
            guild=self.guild,
            requester=self.author,
            bot_user=_bot_user_from_context(self),
            allow_content_wrap=True,
        )
        return await original(self, *args, **kwargs)

    commands.Context.send = send


def _patch_context_reply() -> None:
    original = commands.Context.reply
    _ORIGINALS["context_reply"] = original

    async def reply(self: commands.Context, *args, **kwargs):
        args, kwargs = premium_style.style_kwargs(
            args,
            kwargs,
            command=self.command,
            guild=self.guild,
            requester=self.author,
            bot_user=_bot_user_from_context(self),
            allow_content_wrap=True,
        )
        return await original(self, *args, **kwargs)

    commands.Context.reply = reply


def _patch_messageable_send(bot: commands.Bot) -> None:
    original = discord.abc.Messageable.send
    _ORIGINALS["messageable_send"] = original

    async def send(self, *args, **kwargs):
        guild = _guild_from_messageable(self)
        args, kwargs = premium_style.style_kwargs(
            args,
            kwargs,
            guild=guild,
            bot_user=bot.user,
            allow_content_wrap=False,
        )
        return await original(self, *args, **kwargs)

    discord.abc.Messageable.send = send


def _patch_message_edit(bot: commands.Bot) -> None:
    original = discord.Message.edit
    _ORIGINALS["message_edit"] = original

    async def edit(self: discord.Message, *args, **kwargs):
        args, kwargs = premium_style.style_kwargs(
            args,
            kwargs,
            guild=self.guild,
            bot_user=bot.user,
            allow_content_wrap=False,
        )
        return await original(self, *args, **kwargs)

    discord.Message.edit = edit


def _patch_interaction_response(bot: commands.Bot) -> None:
    original_send = discord.InteractionResponse.send_message
    original_edit = discord.InteractionResponse.edit_message
    _ORIGINALS["interaction_send"] = original_send
    _ORIGINALS["interaction_edit"] = original_edit

    async def send_message(self: discord.InteractionResponse, *args, **kwargs):
        interaction = getattr(self, "_parent", None)
        args, kwargs = premium_style.style_kwargs(
            args,
            kwargs,
            command=getattr(interaction, "command", None),
            guild=getattr(interaction, "guild", None),
            requester=getattr(interaction, "user", None),
            bot_user=bot.user,
            allow_content_wrap=True,
        )
        return await original_send(self, *args, **kwargs)

    async def edit_message(self: discord.InteractionResponse, *args, **kwargs):
        interaction = getattr(self, "_parent", None)
        args, kwargs = premium_style.style_kwargs(
            args,
            kwargs,
            command=getattr(interaction, "command", None),
            guild=getattr(interaction, "guild", None),
            requester=getattr(interaction, "user", None),
            bot_user=bot.user,
            allow_content_wrap=False,
        )
        return await original_edit(self, *args, **kwargs)

    discord.InteractionResponse.send_message = send_message
    discord.InteractionResponse.edit_message = edit_message


def _patch_interaction_edits(bot: commands.Bot) -> None:
    original_edit_original = discord.Interaction.edit_original_response
    _ORIGINALS["interaction_edit_original"] = original_edit_original

    async def edit_original_response(self: discord.Interaction, *args, **kwargs):
        args, kwargs = premium_style.style_kwargs(
            args,
            kwargs,
            command=getattr(self, "command", None),
            guild=self.guild,
            requester=self.user,
            bot_user=bot.user,
            allow_content_wrap=False,
        )
        return await original_edit_original(self, *args, **kwargs)

    discord.Interaction.edit_original_response = edit_original_response


def _patch_webhook_followups(bot: commands.Bot) -> None:
    original = discord.Webhook.send
    _ORIGINALS["webhook_send"] = original

    async def send(self: discord.Webhook, *args, **kwargs):
        # Les webhooks entrants utilisés pour republier un contenu externe ne sont pas
        # des réponses d'interaction et doivent rester exactement tels que configurés.
        if getattr(self, "type", None) == discord.WebhookType.application:
            args, kwargs = premium_style.style_kwargs(
                args,
                kwargs,
                bot_user=bot.user,
                allow_content_wrap=True,
            )
        return await original(self, *args, **kwargs)

    discord.Webhook.send = send


def _patch_design_system() -> None:
    """Fait converger l'ancien design_system vers le moteur unique."""
    try:
        from utils import design_system
    except Exception:
        return

    original_create = design_system.create_embed
    _ORIGINALS["design_create_embed"] = original_create

    def create_embed(*, title, description=None, colour=0x5865F2, user=None, thumbnail=None, footer=None):
        embed = discord.Embed(title=title, description=description, colour=discord.Colour(colour))
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        if footer:
            embed.set_footer(text=footer)
        return premium_style.style_embed(embed, requester=user)

    design_system.create_embed = create_embed


def _patch_log_service() -> None:
    """Applique une identité audit cohérente à toutes les catégories de journaux."""
    try:
        from utils import log_service
    except Exception:
        return

    original = log_service.send_log
    _ORIGINALS["log_service_send"] = original
    category_by_type = {
        "moderation": "moderation",
        "tickets": "tickets",
        "automod": "security",
        "security": "security",
        "economy": "economy",
        "levels": "levels",
        "ai": "ai",
        "games": "games",
    }

    async def send_log(bot, guild, log_type, embed, file=None):
        if isinstance(embed, discord.Embed):
            premium_style.style_embed(
                embed,
                guild=guild,
                bot_user=getattr(bot, "user", None),
                category=category_by_type.get(str(log_type), "logs"),
                log_type=str(log_type),
            )
        return await original(bot, guild, log_type, embed, file=file)

    log_service.send_log = send_log


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    _patch_context_send()
    _patch_context_reply()
    _patch_messageable_send(bot)
    _patch_message_edit(bot)
    _patch_interaction_response(bot)
    _patch_interaction_edits(bot)
    _patch_webhook_followups(bot)
    _patch_design_system()
    _patch_log_service()

    logger.info(
        "Identité premium SentriX installée : commandes, interactions, éditions, MP, panneaux et logs harmonisés."
    )
