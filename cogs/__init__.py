"""Initialisation commune des cogs SentriX."""

from discord.ext import commands

from .dashboard_access import install_dashboard_access
from .poll_ui import install_poll_ui
from .premium_style_runtime import install as install_premium_style
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
        await install_dashboard_access(bot)
    if name == "cogs.server_builder" or name.endswith(".server_builder"):
        await install_server_builder_everyone_ping(bot)
    # embed_builder est le dernier module de main. Installer le moteur ici garantit que
    # toutes les commandes, vues persistantes et interactions ont déjà été enregistrées.
    if name == "cogs.embed_builder" or name.endswith(".embed_builder"):
        install_premium_style(bot)
    return result


if not getattr(commands.Bot, "_sentrix_extension_loader", False):
    commands.Bot.load_extension = _load_extension_with_sentrix_patches
    commands.Bot._sentrix_extension_loader = True
