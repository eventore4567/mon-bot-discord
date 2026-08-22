"""Politique finale de cohérence des réponses SentriX.

Les réponses de commandes qui peuvent être présentées proprement restent dans un embed
Discord. Les modifications d'un message riche effacent aussi l'ancien contenu texte afin
d'éviter qu'une même commande apparaisse parfois avec un cadre et parfois sans cadre.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any

import discord
from discord.ext import commands

from utils import premium_style


_COMMAND_CONTEXT: ContextVar[commands.Context | None] = ContextVar(
    "sentrix_rich_command_context",
    default=None,
)


RICH_ROOTS = frozenset({
    "help", "setup", "ticketsetup", "ticketpanel", "tickettype", "ticketform",
    "ticketconfig", "logsetup", "aisetup", "aidiag", "designsetup", "embed",
    "embed-builder", "shoppanel", "rolepanel", "verify-panel", "create",
    "status", "bot-status", "about", "design-theme", "profile-card", "iconsetup",
})


def _content(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if kwargs.get("content") is not None:
        return kwargs["content"]
    return args[0] if args else None


def _force_rich_args(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    command: Any = None,
    guild: discord.Guild | None = None,
    requester: Any = None,
    bot_user: Any = None,
    include_brand_asset: bool = False,
):
    """Force toute réponse textuelle de commande dans la même carte que +help.

    premium_style évitait volontairement les textes avec mention, URL ou fichier. C'était
    précisément la raison pour laquelle certaines commandes restaient en texte libre. Le
    transport final sait qu'il traite une commande : il peut donc toujours construire la
    carte, tout en laissant les pièces jointes, vues et paramètres Discord intacts.
    """
    args, kwargs = premium_style.style_kwargs(
        args,
        kwargs,
        command=command,
        guild=guild,
        requester=requester,
        bot_user=bot_user,
        allow_content_wrap=True,
    )
    mutable = list(args)
    missing = getattr(discord.utils, "MISSING", object())
    has_embed = kwargs.get("embed") is not None or bool(kwargs.get("embeds"))
    content = kwargs.get("content", missing)
    if content is missing and mutable:
        content = mutable[0]

    if not has_embed and content is not missing and content is not None and str(content).strip():
        kwargs["embed"] = premium_style.content_embed(
            content,
            command=command,
            guild=guild,
            requester=requester,
            bot_user=bot_user,
        )
        if mutable:
            mutable[0] = None
            kwargs.pop("content", None)
        else:
            kwargs["content"] = None

    args, kwargs = premium_style.style_kwargs(
        tuple(mutable),
        kwargs,
        command=command,
        guild=guild,
        requester=requester,
        bot_user=bot_user,
        allow_content_wrap=False,
        include_brand_asset=include_brand_asset,
    )
    if kwargs.get("embed") is not None or kwargs.get("embeds"):
        if not args or args[0] is None:
            kwargs.setdefault("content", None)
    return args, kwargs


def _rich_send_args(ctx: commands.Context, args: tuple[Any, ...], kwargs: dict[str, Any]):
    """Applique à toutes les commandes la même carte compacte que +help."""
    return _force_rich_args(
        args,
        kwargs,
        command=getattr(ctx, "command", None),
        guild=getattr(ctx, "guild", None),
        requester=getattr(ctx, "author", None),
        bot_user=getattr(getattr(ctx, "bot", None), "user", None),
        include_brand_asset=True,
    )


def _root_from_command(command: Any) -> str:
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


def _unwrap(callable_obj):
    """Retrouve prudemment la méthode discord.py sous les anciens wrappers SentriX."""
    seen: set[int] = set()
    current = callable_obj
    while hasattr(current, "_sentrix_original") and id(current) not in seen:
        seen.add(id(current))
        current = getattr(current, "_sentrix_original")
    return current


def _clean_send_args(args: tuple[Any, ...], kwargs: dict[str, Any]):
    """Conserve le nettoyage visuel même lorsque les anciens transports sont contournés."""
    try:
        from . import command_no_emoji_runtime
        return command_no_emoji_runtime._clean_send_args(args, kwargs)
    except Exception:
        return args, kwargs


def _clean_edit_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        from . import command_no_emoji_runtime
        return command_no_emoji_runtime._clean_edit_kwargs(kwargs)
    except Exception:
        return kwargs


def _style_interaction_args(
    interaction: discord.Interaction | None,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    include_brand_asset: bool = False,
):
    args, kwargs = _force_rich_args(
        args,
        kwargs,
        command=getattr(interaction, "command", None),
        guild=getattr(interaction, "guild", None),
        requester=getattr(interaction, "user", None),
        bot_user=getattr(getattr(interaction, "client", None), "user", None),
        include_brand_asset=include_brand_asset,
    )
    return _clean_send_args(args, kwargs)


def install(bot: commands.Bot | None = None) -> None:
    """S'installe en dernier et reste idempotent malgré les nombreux finaliseurs runtime."""
    try:
        from . import premium_style_runtime
        originals = premium_style_runtime._ORIGINALS
    except Exception:
        originals = {}

    # Ce contexte est posé tout à la fin du chargement, après les anciens runtimes. Il
    # identifie aussi les commandes qui répondent avec ctx.channel.send(...) plutôt que
    # ctx.send(...), afin qu'elles reçoivent exactement le même embed.
    current_command_invoke = commands.Command.invoke
    if not getattr(current_command_invoke, "_sentrix_rich_command_scope", False):
        async def absolute_command_invoke(self, ctx: commands.Context):
            token = _COMMAND_CONTEXT.set(ctx)
            try:
                return await current_command_invoke(self, ctx)
            finally:
                _COMMAND_CONTEXT.reset(token)

        absolute_command_invoke._sentrix_rich_command_scope = True
        absolute_command_invoke._sentrix_original = current_command_invoke
        commands.Command.invoke = absolute_command_invoke

    current_group_invoke = commands.Group.invoke
    if not getattr(current_group_invoke, "_sentrix_rich_command_scope", False):
        async def absolute_group_invoke(self, ctx: commands.Context):
            token = _COMMAND_CONTEXT.set(ctx)
            try:
                return await current_group_invoke(self, ctx)
            finally:
                _COMMAND_CONTEXT.reset(token)

        absolute_group_invoke._sentrix_rich_command_scope = True
        absolute_group_invoke._sentrix_original = current_group_invoke
        commands.Group.invoke = absolute_group_invoke

    # Les méthodes sauvegardées par premium_style_runtime sont les vrais transports
    # discord.py, capturés avant community_v32/v33/v34 et les autres politiques. Tous les
    # chemins de commande finissent désormais sur ces mêmes méthodes brutes.
    current_send = commands.Context.send
    raw_context_send = originals.get("context_send") or _unwrap(current_send)
    if not getattr(current_send, "_sentrix_absolute_rich", False):
        async def absolute_context_send(self: commands.Context, *args, **kwargs):
            args, kwargs = _rich_send_args(self, args, kwargs)
            args, kwargs = _clean_send_args(args, kwargs)
            interaction = getattr(self, "interaction", None)
            root = _root_from_command(getattr(self, "command", None))
            if interaction is not None and root:
                try:
                    from . import community_v34
                    if root not in community_v34.SHARED_SLASH_ROOTS:
                        kwargs.setdefault("ephemeral", True)
                except Exception:
                    pass
            result = await raw_context_send(self, *args, **kwargs)
            # command_response_guard est volontairement contourné avec les vieux wrappers.
            # On conserve donc explicitement son marqueur anti-réponse de secours/doublon.
            self._sentrix_response_sent = True
            return result

        absolute_context_send._sentrix_absolute_rich = True
        absolute_context_send._sentrix_rich_response_policy = True
        absolute_context_send._sentrix_plain_response_policy = True
        absolute_context_send._sentrix_response_marker = True
        absolute_context_send._sentrix_original = raw_context_send
        commands.Context.send = absolute_context_send

    current_edit = discord.Message.edit
    raw_message_edit = originals.get("message_edit") or _unwrap(current_edit)
    if not getattr(current_edit, "_sentrix_absolute_rich", False):
        async def absolute_message_edit(self: discord.Message, *args, **kwargs):
            ctx = _COMMAND_CONTEXT.get()
            args, kwargs = _force_rich_args(
                args,
                kwargs,
                command=getattr(ctx, "command", None),
                guild=getattr(self, "guild", None),
                requester=getattr(ctx, "author", None),
                bot_user=getattr(bot, "user", None),
            )
            kwargs = _clean_edit_kwargs(kwargs)
            if kwargs.get("embed") is not None or kwargs.get("embeds"):
                kwargs.setdefault("content", None)
            return await raw_message_edit(self, *args, **kwargs)

        absolute_message_edit._sentrix_absolute_rich = True
        absolute_message_edit._sentrix_rich_response_policy = True
        absolute_message_edit._sentrix_original = raw_message_edit
        discord.Message.edit = absolute_message_edit

    # Couvre aussi les commandes historiques qui utilisent ctx.channel.send(...) au lieu
    # de ctx.send(...). Hors commande, les messages automatiques configurés par les membres
    # gardent leur comportement actuel.
    current_messageable_send = discord.abc.Messageable.send
    raw_messageable_send = originals.get("messageable_send") or _unwrap(current_messageable_send)
    if not getattr(current_messageable_send, "_sentrix_absolute_rich", False):
        async def absolute_messageable_send(self, *args, **kwargs):
            ctx = _COMMAND_CONTEXT.get()
            in_command = ctx is not None
            has_embed = kwargs.get("embed") is not None or bool(kwargs.get("embeds"))
            if not in_command and not has_embed:
                return await current_messageable_send(self, *args, **kwargs)
            args, kwargs = _force_rich_args(
                args,
                kwargs,
                command=getattr(ctx, "command", None),
                guild=getattr(self, "guild", None),
                requester=getattr(ctx, "author", None),
                bot_user=getattr(bot, "user", None),
                include_brand_asset=True,
            )
            if in_command:
                args, kwargs = _clean_send_args(args, kwargs)
            return await raw_messageable_send(self, *args, **kwargs)

        absolute_messageable_send._sentrix_absolute_rich = True
        absolute_messageable_send._sentrix_original = raw_messageable_send
        discord.abc.Messageable.send = absolute_messageable_send

    raw_response_send = originals.get("interaction_send")
    raw_response_edit = originals.get("interaction_edit")

    current_response_send = discord.InteractionResponse.send_message
    if raw_response_send is not None and not getattr(current_response_send, "_sentrix_absolute_rich", False):
        async def absolute_response_send(self: discord.InteractionResponse, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            args, kwargs = _style_interaction_args(
                interaction, args, kwargs, include_brand_asset=True,
            )
            root = _root_from_interaction(interaction)
            if root:
                try:
                    from . import community_v34
                    if root not in community_v34.SHARED_SLASH_ROOTS:
                        kwargs.setdefault("ephemeral", True)
                except Exception:
                    pass
            return await raw_response_send(self, *args, **kwargs)

        absolute_response_send._sentrix_absolute_rich = True
        absolute_response_send._sentrix_original = raw_response_send
        discord.InteractionResponse.send_message = absolute_response_send

    current_response_edit = discord.InteractionResponse.edit_message
    if raw_response_edit is not None and not getattr(current_response_edit, "_sentrix_absolute_rich", False):
        async def absolute_response_edit(self: discord.InteractionResponse, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            args, kwargs = _style_interaction_args(interaction, args, kwargs)
            return await raw_response_edit(self, *args, **kwargs)

        absolute_response_edit._sentrix_absolute_rich = True
        absolute_response_edit._sentrix_original = raw_response_edit
        discord.InteractionResponse.edit_message = absolute_response_edit

    # Réponses après defer() et follow-ups slash : mêmes règles, même embed, même transport.
    current_original_edit = discord.Interaction.edit_original_response
    raw_original_edit = originals.get("interaction_edit_original") or _unwrap(current_original_edit)
    if not getattr(current_original_edit, "_sentrix_absolute_rich", False):
        async def absolute_original_edit(self: discord.Interaction, *args, **kwargs):
            args, kwargs = _style_interaction_args(self, args, kwargs)
            return await raw_original_edit(self, *args, **kwargs)

        absolute_original_edit._sentrix_absolute_rich = True
        absolute_original_edit._sentrix_original = raw_original_edit
        discord.Interaction.edit_original_response = absolute_original_edit

    current_webhook_send = discord.Webhook.send
    raw_webhook_send = originals.get("webhook_send") or _unwrap(current_webhook_send)
    if not getattr(current_webhook_send, "_sentrix_absolute_rich", False):
        async def absolute_webhook_send(self: discord.Webhook, *args, **kwargs):
            if getattr(self, "type", None) != discord.WebhookType.application:
                return await current_webhook_send(self, *args, **kwargs)
            args, kwargs = _force_rich_args(
                args,
                kwargs,
                bot_user=getattr(bot, "user", None),
                include_brand_asset=True,
            )
            args, kwargs = _clean_send_args(args, kwargs)
            return await raw_webhook_send(self, *args, **kwargs)

        absolute_webhook_send._sentrix_absolute_rich = True
        absolute_webhook_send._sentrix_original = raw_webhook_send
        discord.Webhook.send = absolute_webhook_send
