"""Transport canonique des réponses de commandes SentriX.

Une seule couche possède désormais les transports de commandes : + et / passent par
``utils.command_ui_policy``. Les logs, webhooks serveur ordinaires et messages d'événements
ne sont pas transformés ici. Les erreurs sont la responsabilité exclusive de
``cogs.command_error_policy``.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from utils import command_ui_policy
from . import community_v34, permission_guard

logger = logging.getLogger("bot.command-transport")


def _unwrap(callable_obj):
    """Retire uniquement les anciens wrappers SentriX qui exposent leur original."""
    seen: set[int] = set()
    current = callable_obj
    while hasattr(current, "_sentrix_original") and id(current) not in seen:
        seen.add(id(current))
        current = getattr(current, "_sentrix_original")
    return current


def _root_from_command(command) -> str:
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or "").casefold()


def _root_from_interaction(interaction: discord.Interaction | None) -> str:
    if interaction is None:
        return ""
    command = getattr(interaction, "command", None)
    if command is not None:
        return _root_from_command(command)
    data = getattr(interaction, "data", None)
    return str(data.get("name") or "").casefold() if isinstance(data, dict) else ""


def _style_context(ctx: commands.Context, args: tuple, kwargs: dict):
    return command_ui_policy.style_kwargs(
        args,
        kwargs,
        command=getattr(ctx, "command", None),
        guild=getattr(ctx, "guild", None),
        requester=getattr(ctx, "author", None),
        bot_user=getattr(getattr(ctx, "bot", None), "user", None),
        allow_content_wrap=True,
        include_brand_asset=True,
    )


def _style_interaction(interaction: discord.Interaction | None, args: tuple, kwargs: dict, *, wrap: bool):
    return command_ui_policy.style_kwargs(
        args,
        kwargs,
        command=getattr(interaction, "command", None),
        guild=getattr(interaction, "guild", None),
        requester=getattr(interaction, "user", None),
        bot_user=getattr(getattr(interaction, "client", None), "user", None),
        allow_content_wrap=wrap,
        include_brand_asset=wrap,
    )


def _install_context_transport() -> None:
    current_send = commands.Context.send
    if not getattr(current_send, "_sentrix_canonical_transport", False):
        base_send = _unwrap(current_send)

        async def send(self: commands.Context, *args, **kwargs):
            args, kwargs = _style_context(self, args, kwargs)
            result = await base_send(self, *args, **kwargs)
            self._sentrix_response_sent = True
            return result

        send._sentrix_canonical_transport = True
        send._sentrix_original = base_send
        commands.Context.send = send

    current_reply = commands.Context.reply
    if not getattr(current_reply, "_sentrix_canonical_transport", False):
        base_reply = _unwrap(current_reply)

        async def reply(self: commands.Context, *args, **kwargs):
            args, kwargs = _style_context(self, args, kwargs)
            result = await base_reply(self, *args, **kwargs)
            self._sentrix_response_sent = True
            return result

        reply._sentrix_canonical_transport = True
        reply._sentrix_original = base_reply
        commands.Context.reply = reply


def _install_interaction_transport() -> None:
    current_send = discord.InteractionResponse.send_message
    if not getattr(current_send, "_sentrix_canonical_transport", False):
        base_send = _unwrap(current_send)

        async def send_message(self: discord.InteractionResponse, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            args, kwargs = _style_interaction(interaction, args, kwargs, wrap=True)
            return await base_send(self, *args, **kwargs)

        send_message._sentrix_canonical_transport = True
        send_message._sentrix_original = base_send
        discord.InteractionResponse.send_message = send_message

    current_edit = discord.InteractionResponse.edit_message
    if not getattr(current_edit, "_sentrix_canonical_transport", False):
        base_edit = _unwrap(current_edit)

        async def edit_message(self: discord.InteractionResponse, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            args, kwargs = _style_interaction(interaction, args, kwargs, wrap=False)
            if kwargs.get("embed") is not None or kwargs.get("embeds"):
                kwargs.setdefault("content", None)
            return await base_edit(self, *args, **kwargs)

        edit_message._sentrix_canonical_transport = True
        edit_message._sentrix_original = base_edit
        discord.InteractionResponse.edit_message = edit_message

    current_original = discord.Interaction.edit_original_response
    if not getattr(current_original, "_sentrix_canonical_transport", False):
        base_original = _unwrap(current_original)

        async def edit_original_response(self: discord.Interaction, *args, **kwargs):
            args, kwargs = _style_interaction(self, args, kwargs, wrap=False)
            if kwargs.get("embed") is not None or kwargs.get("embeds"):
                kwargs.setdefault("content", None)
            return await base_original(self, *args, **kwargs)

        edit_original_response._sentrix_canonical_transport = True
        edit_original_response._sentrix_original = base_original
        discord.Interaction.edit_original_response = edit_original_response

    current_webhook = discord.Webhook.send
    if not getattr(current_webhook, "_sentrix_canonical_transport", False):
        base_webhook = _unwrap(current_webhook)

        async def webhook_send(self: discord.Webhook, *args, **kwargs):
            # Seulement les followups d'application Discord. Les vrais webhooks serveur et
            # les logs gardent leur payload exact.
            if getattr(self, "type", None) == discord.WebhookType.application:
                args, kwargs = command_ui_policy.style_kwargs(
                    args,
                    kwargs,
                    allow_content_wrap=True,
                    include_brand_asset=True,
                )
            return await base_webhook(self, *args, **kwargs)

        webhook_send._sentrix_canonical_transport = True
        webhook_send._sentrix_original = base_webhook
        discord.Webhook.send = webhook_send


async def _permission_denial(interaction: discord.Interaction, decision) -> None:
    embed = discord.Embed(
        title="Accès refusé",
        description=str(getattr(decision, "reason", None) or "Tu n'as pas accès à cette commande."),
        colour=discord.Colour(0xED4245),
    )
    embed = command_ui_policy.style_embed(
        embed,
        command=getattr(interaction, "command", None),
        guild=getattr(interaction, "guild", None),
        requester=getattr(interaction, "user", None),
        bot_user=getattr(getattr(interaction, "client", None), "user", None),
        kind="danger",
    )
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException, discord.InteractionResponded):
        logger.debug("Refus de permission impossible à envoyer.", exc_info=True)


def _install_permission_denial() -> None:
    permission_guard._send_interaction_denial = _permission_denial


def _install_v34_runtime_only(bot: commands.Bot) -> None:
    """Conserve la fiabilité slash et le routage IA, jamais les anciens renderers V3.4."""
    try:
        community_v34._install_slash_watchdog_policy(bot)
        community_v34._install_fast_ai(bot)
    except Exception:
        logger.exception("Briques runtime V3.4 utiles impossibles à installer.")


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_canonical_transport_installed", False):
        _install_permission_denial()
        return
    _install_v34_runtime_only(bot)
    _install_context_transport()
    _install_interaction_transport()
    _install_permission_denial()
    bot._sentrix_canonical_transport_installed = True
    bot._sentrix_command_transport_owner = "cogs.final_interaction_policy"
    logger.info("Transport canonique actif : une seule chaîne +/slash, erreurs séparées, logs intacts.")


__all__ = ["install"]
