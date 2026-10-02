"""Blocage des commandes SentriX par salon, commun aux commandes + et /."""
from __future__ import annotations

import inspect
import logging

import discord
from discord.ext import commands

from utils import sentrix_panels as panels

logger = logging.getLogger("bot.command-channel-gate")
BLOCKED_MESSAGE = "Les commandes sont désactivées dans ce salon."


class CommandChannelBlocked(commands.CheckFailure):
    """Le garde a déjà répondu en texte brut : aucun rendu d'erreur à ajouter."""


async def is_command_channel_blocked(
    bot: commands.Bot,
    guild_id: int | None,
    channel_id: int | None,
    command_name: str | None = None,
) -> bool:
    if guild_id is None or channel_id is None:
        return False
    try:
        row = await bot.db.fetchone(
            "SELECT 1 FROM command_blocked_channels "
            "WHERE guild_id = ? AND channel_id = ? LIMIT 1",
            (int(guild_id), int(channel_id)),
        )
        if row is not None:
            return True

        name = str(command_name or "").strip().lower()
        if not name:
            return False
        row = await bot.db.fetchone(
            "SELECT 1 FROM command_channel_blocks "
            "WHERE guild_id = ? AND channel_id = ? AND command_name = ? LIMIT 1",
            (int(guild_id), int(channel_id), name),
        )
        return row is not None
    except Exception:
        logger.exception("Lecture des restrictions de commandes par salon impossible.")
        return False


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_command_channel_gate", False):
        return

    async def prefix_gate(ctx: commands.Context) -> bool:
        if getattr(ctx, "command", None) is None or ctx.guild is None:
            return True
        channel_id = getattr(getattr(ctx, "channel", None), "id", None)
        command = getattr(ctx, "command", None)
        root = getattr(command, "root_parent", None) or command
        command_name = str(getattr(root, "name", "") or "").strip().lower()
        if not await is_command_channel_blocked(
            bot, ctx.guild.id, channel_id, command_name
        ):
            return True
        await panels.texte_court(ctx, BLOCKED_MESSAGE)
        raise CommandChannelBlocked(BLOCKED_MESSAGE)

    prefix_gate._sentrix_command_channel_gate = True
    bot.add_check(prefix_gate)

    previous_tree_check = bot.tree.interaction_check

    async def slash_gate(interaction: discord.Interaction) -> bool:
        previous = previous_tree_check(interaction)
        if inspect.isawaitable(previous):
            previous = await previous
        if previous is False:
            return False
        if (
            interaction.type != discord.InteractionType.application_command
            or interaction.guild_id is None
        ):
            return True

        channel_id = (
            getattr(interaction, "channel_id", None)
            or getattr(getattr(interaction, "channel", None), "id", None)
        )
        data = getattr(interaction, "data", None)
        command_name = (
            str(data.get("name") or "").strip().lower()
            if isinstance(data, dict) else ""
        )
        if not await is_command_channel_blocked(
            bot, interaction.guild_id, channel_id, command_name
        ):
            return True

        await panels.texte_court(
            interaction.response,
            BLOCKED_MESSAGE,
            ephemere=True,
        )
        return False

    slash_gate._sentrix_command_channel_gate = True
    slash_gate._sentrix_previous_tree_check = previous_tree_check
    bot.tree.interaction_check = slash_gate
    bot._sentrix_command_channel_gate = True
    logger.info("Blocage des commandes par salon actif pour + et /.")


async def setup(bot: commands.Bot):
    install(bot)


__all__ = [
    "BLOCKED_MESSAGE", "CommandChannelBlocked",
    "is_command_channel_blocked", "install",
]
