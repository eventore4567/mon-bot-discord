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


def _has_non_ping_text(value: Any) -> bool:
    text = _MENTION_RE.sub("", str(value or ""))
    return bool(text.strip(" \n\t,;:|•-—–"))


def _move_content_next_to_existing_embeds(
    kwargs: dict,
    content: Any,
    *,
    root: str,
    bot: Any,
) -> dict:
    """Déplace un ancien ``content + embed`` dans une carte sans perdre l'embed métier."""
    text = str(content or "").strip()
    if not text:
        return kwargs

    existing: list[discord.Embed] = []
    single = kwargs.pop("embed", None)
    if isinstance(single, discord.Embed):
        existing.append(single)
    for item in list(kwargs.pop("embeds", []) or []):
        if isinstance(item, discord.Embed):
            existing.append(item)

    cards = [
        policy._clean_embed(card, root=root, bot=bot)
        for card in policy._cards_from_text(text)
    ]
    cards = [card for card in cards if isinstance(card, discord.Embed)]

    available = max(0, 10 - len(existing))
    if available:
        kwargs["embeds"] = cards[:available] + existing
    elif existing:
        # Cas extrême : Discord autorise déjà 10 embeds. Ne pas en supprimer un ; ajoute
        # le texte à la première carte dans la limite Discord.
        first = existing[0]
        description = str(first.description or "").strip()
        combined = f"{description}\n\n{text}" if description else text
        first.description = combined[:4096]
        kwargs["embeds"] = existing[:10]
    elif cards:
        if len(cards) == 1:
            kwargs["embed"] = cards[0]
        else:
            kwargs["embeds"] = cards[:10]
    return kwargs


def _set_remaining_content(
    args: tuple,
    kwargs: dict,
    *,
    positional: bool,
    value: str | None,
) -> tuple[tuple, dict]:
    mutable_args = list(args)
    if positional and mutable_args:
        mutable_args[0] = value
        kwargs.pop("content", None)
    else:
        kwargs["content"] = value
    return tuple(mutable_args), kwargs


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
    original_had_embed = (
        isinstance(original_kwargs.get("embed"), discord.Embed)
        or bool(original_kwargs.get("embeds"))
    )

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

    if original_content is not None and str(original_content).strip():
        # Le renderer officiel transforme déjà le texte lorsqu'il n'y avait PAS d'embed.
        # Le cas historique ``content + embed`` doit être traité ici explicitement.
        if original_had_embed and (not ping_requested or _has_non_ping_text(original_content)):
            new_kwargs = _move_content_next_to_existing_embeds(
                new_kwargs,
                original_content,
                root=root,
                bot=bot,
            )

        remaining = _ping_stub(original_content) if ping_requested else None
        new_args, new_kwargs = _set_remaining_content(
            new_args,
            new_kwargs,
            positional=positional,
            value=remaining,
        )

    # Résultat : tout texte lisible d'une commande est dans un embed. Le seul ``content``
    # encore permis est une suite de mentions lorsqu'un vrai ping a été demandé.
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


__all__ = [
    "install",
    "_normalize_command_payload",
    "_ping_stub",
    "_has_non_ping_text",
]
