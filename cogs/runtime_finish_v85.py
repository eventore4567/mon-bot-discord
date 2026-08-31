"""V85 — correctif de portée du preset manox et installation de V84."""
from __future__ import annotations

import discord
from discord.ext import commands

from . import runtime_finish_v84 as v84


def _find_channel_scoped(
    guild: discord.Guild,
    name: str,
    kind: str,
    category: discord.CategoryChannel | None,
):
    if kind == "text":
        candidates = list(guild.text_channels)
    elif kind == "stage":
        candidates = list(getattr(guild, "stage_channels", [])) + list(guild.voice_channels)
    else:
        candidates = list(guild.voice_channels)

    exact = [channel for channel in candidates if channel.name == name]
    if category is None:
        return next((channel for channel in exact if channel.category_id is None), None)
    return next((channel for channel in exact if channel.category_id == category.id), None)


def install(bot: commands.Bot) -> None:
    v84._find_channel = _find_channel_scoped
    v84.install(bot)


__all__ = ["install"]
