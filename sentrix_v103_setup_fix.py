"""SentriX V103 — correctif final de /setup.

Le centre de configuration possède déjà une implémentation native dans
``cogs.setup_control_center``. Certaines couches de compatibilité remplaçaient toutefois
cette route par un pont vers la commande préfixée ``+setup``. Si la signature legacy
était repolluée par ``ctx``/``*args``/``**kwargs``, ``Command.invoke`` demandait alors
``ctx`` à l'utilisateur et Discord affichait « Information manquante ».

V103 s'exécute après les couches V95–V102 : il laisse d'abord toute la surface slash se
construire, puis réinstalle /setup comme route native sans aucun argument utilisateur.
"""
from __future__ import annotations

import inspect
import logging

import discord
from discord import app_commands

import sentrix_v95_runtime as v95

logger = logging.getLogger("bot.v103-setup-fix")
_INSTALLED = False


def _replace_setup_slash(bot) -> bool:
    """Réinstalle /setup en appelant directement le contrôleur officiel."""
    cog = bot.get_cog("SentriXSetup")
    sender = getattr(cog, "send_setup", None) if cog is not None else None
    if not callable(sender):
        logger.error("V103 : cog SentriXSetup/send_setup introuvable ; /setup non remplacé.")
        return False

    tree = bot.tree
    try:
        tree.remove_command("setup", type=discord.AppCommandType.chat_input)
    except TypeError:
        tree.remove_command("setup")

    async def setup_callback(interaction: discord.Interaction) -> None:
        # On relit le Cog à chaque invocation pour ne jamais conserver une ancienne
        # instance si Discord.py recharge la configuration.
        current_cog = bot.get_cog("SentriXSetup")
        current_sender = (
            getattr(current_cog, "send_setup", None)
            if current_cog is not None
            else None
        )
        if not callable(current_sender):
            raise RuntimeError("Le centre de configuration SentriX n'est pas chargé.")
        await current_sender(interaction)

    setup_callback.__name__ = "slash_setup_v103"
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

    tree.add_command(
        app_commands.Command(
            name="setup",
            description="Ouvrir le centre de configuration SentriX",
            callback=setup_callback,
        ),
        override=True,
    )
    logger.info("V103 : /setup natif installé sans ctx/args/kwargs.")
    return True


def install() -> None:
    """Place le correctif après toutes les transformations de ``prepare_bot``."""
    global _INSTALLED
    if _INSTALLED:
        return

    current_prepare = v95.prepare_bot
    if getattr(current_prepare, "_sentrix_v103_setup_fix", False):
        _INSTALLED = True
        return

    async def prepare_bot_v103(bot):
        result = await current_prepare(bot)
        _replace_setup_slash(bot)
        return result

    prepare_bot_v103._sentrix_v103_setup_fix = True
    prepare_bot_v103._sentrix_original = current_prepare
    v95.prepare_bot = prepare_bot_v103
    _INSTALLED = True
    logger.info("V103 setup fix armé.")


__all__ = ["install", "_replace_setup_slash"]
