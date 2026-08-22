"""Politique finale de cohérence des réponses SentriX.

Les réponses de commandes qui peuvent être présentées proprement restent dans un embed
Discord. Les modifications d'un message riche effacent aussi l'ancien contenu texte afin
d'éviter qu'une même commande apparaisse parfois avec un cadre et parfois sans cadre.
"""
from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands

from utils import premium_style


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


def _rich_send_args(ctx: commands.Context, args: tuple[Any, ...], kwargs: dict[str, Any]):
    """Transforme uniquement le texte compatible ; fichiers et mentions restent intacts."""
    args = list(args)
    kwargs = dict(kwargs)
    args, kwargs = premium_style.style_kwargs(
        tuple(args),
        kwargs,
        command=getattr(ctx, "command", None),
        guild=getattr(ctx, "guild", None),
        requester=getattr(ctx, "author", None),
        bot_user=getattr(getattr(ctx, "bot", None), "user", None),
        allow_content_wrap=True,
        include_brand_asset=True,
    )
    args = list(args)

    # Si un embed est explicitement fourni, il devient l'unique présentation visuelle.
    # Cela empêche un ancien texte de rester au-dessus après une modification.
    if kwargs.get("embed") is not None or kwargs.get("embeds"):
        if not args or args[0] is None:
            kwargs.setdefault("content", None)
    return tuple(args), kwargs


def install(bot: commands.Bot | None = None) -> None:
    """S'installe en dernier et reste idempotent malgré les nombreux finaliseurs runtime."""
    current_send = commands.Context.send
    if not getattr(current_send, "_sentrix_rich_response_policy", False):
        async def rich_send(self: commands.Context, *args, **kwargs):
            args, kwargs = _rich_send_args(self, args, kwargs)
            return await current_send(self, *args, **kwargs)

        rich_send._sentrix_rich_response_policy = True
        rich_send._sentrix_plain_response_policy = True
        rich_send._sentrix_original = current_send
        commands.Context.send = rich_send

    current_edit = discord.Message.edit
    if not getattr(current_edit, "_sentrix_rich_response_policy", False):
        async def rich_edit(self: discord.Message, *args, **kwargs):
            kwargs = dict(kwargs)
            if kwargs.get("embed") is not None or kwargs.get("embeds"):
                kwargs.setdefault("content", None)
            return await current_edit(self, *args, **kwargs)

        rich_edit._sentrix_rich_response_policy = True
        rich_edit._sentrix_original = current_edit
        discord.Message.edit = rich_edit
