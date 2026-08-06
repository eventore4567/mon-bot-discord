"""Initialisation commune des cogs SentriX."""

from discord.ext import commands

from .poll_ui import install_poll_ui


_ORIGINAL_LOAD_EXTENSION = commands.Bot.load_extension


async def _load_extension_with_poll_ui(
    bot: commands.Bot,
    name: str,
    *,
    package: str | None = None,
):
    result = await _ORIGINAL_LOAD_EXTENSION(bot, name, package=package)
    if name == "cogs.utility" or name.endswith(".utility"):
        await install_poll_ui(bot)
    return result


if not getattr(commands.Bot, "_sentrix_poll_ui_loader", False):
    commands.Bot.load_extension = _load_extension_with_poll_ui
    commands.Bot._sentrix_poll_ui_loader = True
