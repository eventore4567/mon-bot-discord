"""Late SentriX regression extension.

The regression layer stays the compatibility base. Product-facing fixes are applied last so
historical cogs cannot re-register ticket setup commands or override the final error policy.
V76 is deliberately installed at the end: it guards the live prefix registry immediately
before invocation, after all older wrappers had a chance to touch it. V77 patches the
already-loaded Invites cog, then V78 replaces the verification entry point with the complete
Discord configurator requested by the server administrators.
"""
import discord

from sentrix_regression_runtime import setup as _regression_setup
from sentrix_product_update import install_runtime
from sentrix_final_product_finish import install as install_final_product_finish
from .command_final_guard_v76 import install as install_command_final_guard_v76
from .invite_detection_fix_v77 import install as install_invite_detection_fix_v77
from .verify_setup_interactive_v78 import install as install_verify_setup_interactive_v78


async def setup(bot):
    await _regression_setup(bot)
    await install_runtime(bot)
    await install_final_product_finish(bot)
    install_command_final_guard_v76(bot)
    install_invite_detection_fix_v77(bot)

    # discord.py représente aussi les salons d'annonces avec TextChannel. Le configurateur
    # V78 accepte ChannelType.news dans son sélecteur ; cet alias évite qu'une ancienne
    # distinction NewsChannel provoque une AttributeError au moment de publier.
    if not hasattr(discord, "NewsChannel"):
        discord.NewsChannel = discord.TextChannel
    install_verify_setup_interactive_v78(bot)


__all__ = ["setup"]
