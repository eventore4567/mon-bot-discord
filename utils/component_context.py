"""Contexte léger pour réutiliser les commandes depuis les boutons Discord."""

from __future__ import annotations

import discord


class ComponentContext:
    # Sans .interaction : sentrix_panels doit passer par send, qui impose le privé.
    interaction = None
    prefix = "/"
    clean_prefix = "/"

    def __init__(self, bot, interaction, *, channel=None):
        self.bot = bot
        self.guild = interaction.guild
        self.author = interaction.user
        self.channel = channel or interaction.channel
        self.message = interaction.message
        self._source = interaction
        self.command = None

    async def send(self, content=None, **kwargs):
        kwargs["ephemeral"] = True
        kwargs.setdefault("allowed_mentions", discord.AllowedMentions.none())
        if content is not None:
            kwargs["content"] = content
        if not self._source.response.is_done():
            await self._source.response.send_message(**kwargs)
            return await self._source.original_response()
        return await self._source.followup.send(**kwargs, wait=True)

    async def reply(self, content=None, **kwargs):
        return await self.send(content, **kwargs)
