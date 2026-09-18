"""SentriX V103 — garde de compatibilité de la route /setup.

Historique : V103 réinstallait autrefois /setup en le redirigeant vers
``cogs.setup_control_center.SentriXSetup``. Depuis le Smart Setup V4/V114, cette route est
obsolète : le setup officiel vit dans ``cogs.configuration.SetupView`` et V113/V114
patchent précisément cette vue pour fournir l'accueil compact, Smart Setup, snapshots,
rollback et diagnostic.

V116 ajoute le centre hiérarchique et redevient l'interface publique de /setup.
La couche V117 reste dans le dépôt pour historique, mais n'est plus installée au runtime.

Cette couche reste utile pour garantir une signature slash sans argument utilisateur après
les transformations V95+, mais elle ne possède plus d'interface concurrente. Elle ouvre
explicitement le panneau du cog Configuration.
"""
from __future__ import annotations

import inspect
import logging

import discord
from discord import app_commands

import config
import sentrix_v95_runtime as v95
from utils import embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.v103-setup-fix")
_INSTALLED = False

# Contrat d'interface publique : le runtime ouvre bien le centre hiérarchique V116.
# Le marqueur d'autorité slash reste volontairement V114 pour compatibilité avec les
# gardes historiques qui vérifient l'unicité de /setup.
PUBLIC_SETUP_UI = "configuration-v116"


async def _is_setup_authorized(bot, interaction: discord.Interaction) -> bool:
    """Même barrière que la commande Configuration.setup_wizard."""
    if interaction.guild is None:
        return False
    user = interaction.user
    if user.id in config.OWNER_IDS:
        return True
    try:
        if await bot.is_owner(user):
            return True
    except Exception:
        pass
    return isinstance(user, discord.Member) and user.guild_permissions.administrator


async def _send_setup_v114(bot, interaction: discord.Interaction) -> None:
    """Ouvre LE centre de configuration : le même que ``+setup``.

    ``/setup`` et ``+setup`` ouvraient deux interfaces différentes (Configuration.SetupView
    d'un côté, setup_control_center.SetupView de l'autre). Il n'y a plus qu'un moteur :
    cogs/setup_control_center.OfficialSetup.send_setup, qui accepte un Context comme une
    Interaction et applique la même autorisation.
    """
    if interaction.guild is None:
        return await interaction.response.send_message(
            "Cette commande doit être utilisée dans un serveur.", ephemeral=True
        )
    setup_cog = bot.get_cog("SentriXSetup")
    if setup_cog is None or not callable(getattr(setup_cog, "send_setup", None)):
        raise RuntimeError("Le centre de configuration (cogs.setup_control_center) n'est pas chargé.")
    await setup_cog.send_setup(interaction)


def _replace_setup_slash(bot) -> bool:
    """Réinstalle /setup avec une signature native, dirigée vers Configuration.SetupView."""
    if bot.get_cog("SentriXSetup") is None:
        logger.error("V103 : cog SentriXSetup (setup_control_center) introuvable ; /setup non remplacé.")
        return False

    tree = bot.tree
    try:
        tree.remove_command("setup", type=discord.AppCommandType.chat_input)
    except TypeError:
        tree.remove_command("setup")

    async def setup_callback(interaction: discord.Interaction) -> None:
        await _send_setup_v114(bot, interaction)

    setup_callback.__name__ = "slash_setup_v114"
    setup_callback.__qualname__ = setup_callback.__name__
    setup_callback.__signature__ = inspect.Signature([
        inspect.Parameter(
            "interaction",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=discord.Interaction,
        )
    ])
    setup_callback.__annotations__ = {
        "interaction": discord.Interaction,
        "return": None,
    }
    setup_callback._sentrix_original_command = "setup"
    setup_callback._sentrix_native_options = True
    setup_callback._sentrix_setup_authority = "configuration-v114"

    tree.add_command(
        app_commands.Command(
            name="setup",
            description="Ouvrir le centre de configuration SentriX (le même que +setup)",
            callback=setup_callback,
        ),
        override=True,
    )
    logger.info("V103 : /setup ouvre le centre de configuration de +setup (moteur unique).")
    return True


def install() -> None:
    """Place la garde après toutes les transformations de ``prepare_bot``."""
    global _INSTALLED
    if _INSTALLED:
        return

    current_prepare = v95.prepare_bot
    if getattr(current_prepare, "_sentrix_v103_setup_fix", False):
        _INSTALLED = True
        return

    async def prepare_bot_v103(bot):
        result = await current_prepare(bot)
        try:
            from sentrix_setup_v116 import install_for_bot as install_setup_v116
            install_setup_v116(bot)
        except Exception:
            logger.exception("Installation du centre Setup V116 impossible.")
        _replace_setup_slash(bot)
        return result

    prepare_bot_v103._sentrix_v103_setup_fix = True
    prepare_bot_v103._sentrix_original = current_prepare
    v95.prepare_bot = prepare_bot_v103
    _INSTALLED = True
    logger.info("V103 setup authority guard armé pour Smart Setup V114/V116.")


__all__ = ["install", "_replace_setup_slash", "_send_setup_v114", "_is_setup_authorized"]
