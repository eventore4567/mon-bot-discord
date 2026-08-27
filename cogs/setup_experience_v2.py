"""Compatibilité de chargement : le centre de contrôle V20 remplace l'ancien patch visuel V2."""
from __future__ import annotations

from discord.ext import commands


async def setup(bot: commands.Bot):
    from . import control_center_v20
    import main as bot_main

    await control_center_v20.setup(bot)

    # plain_text_all_extension réenregistre encore le help historique plus tard pendant le
    # bootstrap. Ajouter le finalizer à la FIN de la liste garantit que V20 redevient la
    # dernière autorité avant le prune, l'audit et tree.sync(), sans dupliquer la logique.
    finalizer = "cogs.control_center_finalizer_v20"
    if finalizer not in bot_main.EXTENSIONS:
        bot_main.EXTENSIONS.append(finalizer)
