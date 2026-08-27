"""Dernière autorité runtime pour +setup / /setup et +help / /help V20.

Le bootstrap historique réenregistre encore son ancien help très tard. Ce finalizer est
ajouté dynamiquement en fin de liste par setup_experience_v2 : il restaure ensuite le
centre V20 et neutralise uniquement la garde on_ready qui tenterait de remettre l'ancien
help. Les autres protections visuelles/finales restent intactes.
"""
from __future__ import annotations

import logging

from discord.ext import commands

logger = logging.getLogger("bot.control-center-v20-final")


async def setup(bot: commands.Bot) -> None:
    from . import control_center_v20

    try:
        from . import plain_text_all_extension

        async def keep_v20_help(_bot: commands.Bot) -> None:
            return None

        plain_text_all_extension._ensure_official_help_on_ready = keep_v20_help
    except Exception:
        logger.debug("Garde help historique non chargée ; aucun remplacement nécessaire.", exc_info=True)

    old = bot.get_cog("SentriXControlCenterV20")
    if old is not None:
        await bot.remove_cog("SentriXControlCenterV20")

    await control_center_v20.setup(bot)
    bot._sentrix_control_center_v20_final = True
    logger.info("Centre de contrôle SentriX V20 réaffirmé en dernière autorité runtime.")
