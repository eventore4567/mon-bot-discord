"""Empêche SentriX de créer des réponses liées à un message supprimable.

Discord affiche « Le message original a été supprimé » lorsqu'un message du bot possède
une MessageReference vers un message ensuite effacé. Cette couche neutralise toutes les
sources habituelles de référence : ctx.reply(), Message.reply() et les send(reference=...).
"""
from __future__ import annotations

import discord
from discord.ext import commands

_INSTALLED = False


def _clean_reference_kwargs(kwargs: dict) -> dict:
    kwargs.pop("reference", None)
    kwargs.pop("mention_author", None)
    kwargs.pop("fail_if_not_exists", None)
    return kwargs


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Les fonctions courantes sont déjà enveloppées par le moteur de style SentriX à ce
    # stade. On enveloppe donc les versions actuelles afin de conserver exactement le même
    # rendu tout en supprimant uniquement la référence Discord.
    context_send = commands.Context.send
    messageable_send = discord.abc.Messageable.send

    async def context_send_without_reference(self: commands.Context, *args, **kwargs):
        return await context_send(self, *args, **_clean_reference_kwargs(kwargs))

    async def context_reply_without_reference(self: commands.Context, *args, **kwargs):
        return await context_send_without_reference(self, *args, **kwargs)

    async def messageable_send_without_reference(self, *args, **kwargs):
        return await messageable_send(self, *args, **_clean_reference_kwargs(kwargs))

    async def message_reply_without_reference(self: discord.Message, *args, **kwargs):
        # Message.reply() ajoute normalement reference=self. On envoie volontairement dans
        # le salon comme un message normal pour qu'une suppression future n'affiche jamais
        # le bandeau « message original supprimé ».
        return await self.channel.send(*args, **_clean_reference_kwargs(kwargs))

    commands.Context.send = context_send_without_reference
    commands.Context.reply = context_reply_without_reference
    discord.abc.Messageable.send = messageable_send_without_reference
    discord.Message.reply = message_reply_without_reference
