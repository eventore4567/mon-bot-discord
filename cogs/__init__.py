"""Initialisation commune des cogs SentriX."""

from discord.ext import commands

from .poll_ui import install_poll_ui
from .server_builder_everyone import install_server_builder_everyone_ping


_ORIGINAL_LOAD_EXTENSION = commands.Bot.load_extension


async def _load_extension_with_sentrix_patches(
    bot: commands.Bot,
    name: str,
    *,
    package: str | None = None,
):
    result = await _ORIGINAL_LOAD_EXTENSION(bot, name, package=package)
    if name == "cogs.utility" or name.endswith(".utility"):
        await install_poll_ui(bot)
    if name == "cogs.server_builder" or name.endswith(".server_builder"):
        await install_server_builder_everyone_ping(bot)
    return result


if not getattr(commands.Bot, "_sentrix_extension_loader", False):
    commands.Bot.load_extension = _load_extension_with_sentrix_patches
    commands.Bot._sentrix_extension_loader = True
