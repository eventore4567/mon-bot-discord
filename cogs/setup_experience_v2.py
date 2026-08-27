"""Compatibilité de chargement : le centre de contrôle V20 remplace l'ancien patch visuel V2."""
from __future__ import annotations

from discord.ext import commands


async def setup(bot: commands.Bot):
    from . import control_center_v20

    await control_center_v20.setup(bot)
