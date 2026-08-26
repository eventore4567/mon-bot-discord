"""Invariant final : toute réponse de commande SentriX est rendue en embed.

Cette garde est installée APRES les autres transports Railway. Elle ne transforme pas les
messages ordinaires du bot hors commande. Pendant une commande préfixée ou slash, elle
couvre Context.send, les envois directs de salon, les réponses/follow-ups d'interaction et
les éditions. Si une commande doit réellement ping, seul le marqueur de mention reste en
contenu ; le texte lisible est déplacé dans l'embed.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from . import final_interaction_policy as policy

logger = logging.getLogger("bot.command-embed-invariant")

_MARKER = "_sentrix_command_embed_invariant_v1"
_MENTION_RE = re.compile(r"<@!?\d{15,22}>|<@&\d{15,22}>|@everyone|@here", re.IGNORECASE)


def _content_from(args: tuple, kwargs: dict) -> tuple[Any, bool]:
    if kwargs.get("content") is not None:
        return kwargs.get("content"), False
    if args:
        return args[0], True
    return None, False


def _ping_stub(value: Any) -> str | None:
    """Conserve uniquement les mentions nécessaires à une vraie notification Discord."""
    seen: set[str] = set()
    tokens: list[str] = []
    for match in _MENTION_RE.findall(str(value or "")):
        key = match.casefold()
        if key in seen:
            continue
        seen.add(key)
        tokens.append(match)
    text = " ".join(tokens).strip()
    return text[:1900] or None


def _normalize_command_payload(
    args: tuple,
    kwargs: dict,
    *,
    editing: bool = False,
    root: str = "",
    bot: Any = None,
):
    """Force l'embed même lorsque allowed_mentions demandait auparavant un bypass."""
    original_kwargs = dict(kwargs)
    original_content, positional = _content_from(args, original_kwargs)
    allowed_mentions = original_kwargs.get("allowed_mentions")
    ping_requested = policy._explicit_ping_requested(original_kwargs)

    work_kwargs = dict(original_kwargs)
    if ping_requested:
        # Le renderer officiel ne convertit volontairement pas les pings. On retire donc
        # temporairement le transport de mention, puis on le remet après conversion.
        work_kwargs.pop("allowed_mentions", None)

    new_args, new_kwargs = policy._normalize_payload(
        args,
        work_kwargs,
        editing=editing,
        force_embed=True,
        root=root,
        bot=bot,
    )

    if allowed_mentions is not None:
        new_kwargs["allowed_mentions"] = allowed_mentions

    if ping_requested and original_content is not None and str(original_content).strip():
        stub = _ping_stub(original_content)
        mutable_args = list(new_args)
        if positional and mutable_args:
            mutable_args[0] = stub
            new_kwargs.pop("content", None)
        else:
            new_kwargs["content"] = stub
        new_args = tuple(mutable_args)

    # Si le payload avait déjà un embed, le normaliseur officiel l'a simplement remis au
    # design SentriX. S'il n'y avait que du texte, il existe maintenant au moins un embed.
    return new_args, new_kwargs


def _root_from_context(ctx: commands.Context | None) -> str:
    if ctx is None:
        return policy._COMMAND_ROOT.get()
    return policy._root_name(getattr(ctx, "command", None)) or policy._COMMAND_ROOT.get()


def _install_app_command_context() -> None:
    current = getattr(app_commands.Command, "_invoke_with_namespace", None)
    if current is None or getattr(current, _MARKER, False):
        return

    async def invoke_with_embed_context(self, interaction: discord.Interaction, *args, **kwargs):
        root = policy._root_from_interaction(interaction) or policy._root_name(self)
        token = policy._COMMAND_ROOT.set(root)
        try:
            return await current(self, interaction, *args, **kwargs)
        finally:
            policy._COMMAND_ROOT.reset(token)

    setattr(invoke_with_embed_context, _MARKER, True)
    invoke_with_embed_context._sentrix_original = current
    app_commands.Command._invoke_with_namespace = invoke_with_embed_context


def _install_context_send() -> None:
    current = commands.Context.send
    if getattr(current, _MARKER, False):
        return

    async def context_send(self: commands.Context, *args, **kwargs):
        root = _root_from_context(self)
        if policy._plain_root(root):
            return await current(self, *args, **kwargs)
        args, kwargs = _normalize_command_payload(
            args, kwargs, root=root, bot=getattr(self, "bot", None)
        )
        return await current(self, *args, **kwargs)

    setattr(context_send, _MARKER, True)
    context_send._sentrix_original = current
    commands.Context.send = context_send


def _install_messageable_send() -> None:
    current = discord.abc.Messageable.send
    if getattr(current, _MARKER, False):
        return

    async def messageable_send(self, *args, **kwargs):
        root = policy._COMMAND_ROOT.get()
        if root and not policy._plain_root(root):
            args, kwargs = _normalize_command_payload(args, kwargs, root=root)
        return await current(self, *args, **kwargs)

    setattr(messageable_send, _MARKER, True)
    messageable_send._sentrix_original = current
    discord.abc.Messageable.send = messageable_send


def _install_message_edit() -> None:
    current = discord.Message.edit
    if getattr(current, _MARKER, False):
        return

    async def message_edit(self: discord.Message, *args, **kwargs):
        root = policy._COMMAND_ROOT.get()
        if root and not policy._plain_root(root):
            args, kwargs = _normalize_command_payload(args, kwargs, editing=True, root=root)
        return await current(self, *args, **kwargs)

    setattr(message_edit, _MARKER, True)
    message_edit._sentrix_original = current
    discord.Message.edit = message_edit


def _install_interaction_responses() -> None:
    current_send = discord.InteractionResponse.send_message
    if not getattr(current_send, _MARKER, False):
        async def response_send(self, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            root = policy._root_from_interaction(interaction) or policy._COMMAND_ROOT.get()
            if policy._plain_root(root):
                return await current_send(self, *args, **kwargs)
            args, kwargs = _normalize_command_payload(
                args, kwargs, root=root, bot=getattr(interaction, "client", None)
            )
            return await current_send(self, *args, **kwargs)

        setattr(response_send, _MARKER, True)
        response_send._sentrix_original = current_send
        discord.InteractionResponse.send_message = response_send

    current_edit = discord.InteractionResponse.edit_message
    if not getattr(current_edit, _MARKER, False):
        async def response_edit(self, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            root = policy._root_from_interaction(interaction) or policy._COMMAND_ROOT.get()
            if policy._plain_root(root):
                return await current_edit(self, *args, **kwargs)
            args, kwargs = _normalize_command_payload(
                args,
                kwargs,
                editing=True,
                root=root,
                bot=getattr(interaction, "client", None),
            )
            return await current_edit(self, *args, **kwargs)

        setattr(response_edit, _MARKER, True)
        response_edit._sentrix_original = current_edit
        discord.InteractionResponse.edit_message = response_edit

    current_original = discord.Interaction.edit_original_response
    if not getattr(current_original, _MARKER, False):
        async def edit_original(self: discord.Interaction, *args, **kwargs):
            root = policy._root_from_interaction(self) or policy._COMMAND_ROOT.get()
            if policy._plain_root(root):
                return await current_original(self, *args, **kwargs)
            args, kwargs = _normalize_command_payload(
                args,
                kwargs,
                editing=True,
                root=root,
                bot=getattr(self, "client", None),
            )
            return await current_original(self, *args, **kwargs)

        setattr(edit_original, _MARKER, True)
        edit_original._sentrix_original = current_original
        discord.Interaction.edit_original_response = edit_original


def _install_followups() -> None:
    current = discord.Webhook.send
    if getattr(current, _MARKER, False):
        return

    async def webhook_send(self: discord.Webhook, *args, **kwargs):
        root = policy._COMMAND_ROOT.get()
        if (
            getattr(self, "type", None) == discord.WebhookType.application
            and root
            and not policy._plain_root(root)
        ):
            args, kwargs = _normalize_command_payload(args, kwargs, root=root)
        return await current(self, *args, **kwargs)

    setattr(webhook_send, _MARKER, True)
    webhook_send._sentrix_original = current
    discord.Webhook.send = webhook_send


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_command_embed_invariant_v1", False):
        return

    _install_app_command_context()
    _install_context_send()
    _install_messageable_send()
    _install_message_edit()
    _install_interaction_responses()
    _install_followups()

    bot._sentrix_command_embed_invariant_v1 = True
    logger.info(
        "Invariant embed V1 actif : toutes les sorties de commandes +/slash sont converties en cartes SentriX."
    )


async def setup(bot: commands.Bot) -> None:
    install(bot)


__all__ = ["install", "_normalize_command_payload", "_ping_stub"]
