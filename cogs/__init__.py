"""Initialisation commune des cogs SentriX."""

from discord.ext import commands

from .afk_nickname import install as install_afk_nickname
from .afk_signature_fix import install as install_afk_signature_fix
from .ai_reliability import install as install_ai_reliability
from .dashboard_access import install_dashboard_access
from .help_complete import install as install_complete_help
from .help_home_circles import install as install_help_home_circles
from .poll_ui import install_poll_ui
from .premium_style_runtime import install as install_premium_style
from .remove_code_command import install as install_remove_code_command
from .server_builder_everyone import install_server_builder_everyone_ping
from .setup_close_fix import install as install_setup_close_fix


_ORIGINAL_LOAD_EXTENSION = commands.Bot.load_extension


async def _load_extension_with_sentrix_patches(
    bot: commands.Bot,
    name: str,
    *,
    package: str | None = None,
):
    result = await _ORIGINAL_LOAD_EXTENSION(bot, name, package=package)

    # Idempotent : le moteur est installé dès le premier cog chargé. Il couvre donc aussi
    # les futurs cogs et reste actif même si un module optionnel échoue plus tard.
    install_premium_style(bot)

    if name == "cogs.ai" or name.endswith(".ai"):
        install_ai_reliability()
        install_remove_code_command(bot)
    if name == "cogs.utility" or name.endswith(".utility"):
        await install_poll_ui(bot)
        # L'aide complète doit être installée avant l'ajout du bouton dashboard afin que
        # celui-ci enveloppe bien la nouvelle page d'accueil dynamique.
        install_complete_help(bot)
        await install_dashboard_access(bot)
        # Le style sobre passe en dernier pour nettoyer aussi le champ et le bouton du
        # dashboard sans modifier leur fonctionnement.
        install_help_home_circles(bot)
        await install_afk_nickname(bot)
        install_afk_signature_fix(bot)
    if name == "cogs.configuration" or name.endswith(".configuration"):
        install_setup_close_fix(bot)
    if name == "cogs.server_builder" or name.endswith(".server_builder"):
        await install_server_builder_everyone_ping(bot)
    return result


if not getattr(commands.Bot, "_sentrix_extension_loader", False):
    commands.Bot.load_extension = _load_extension_with_sentrix_patches
    commands.Bot._sentrix_extension_loader = True
