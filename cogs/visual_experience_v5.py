"""SentriX visual V5 bootstrap.

Keeps the existing V5 experience intact and loads the Community+ parity pack.
"""
from __future__ import annotations

from . import cosmos_parity
from . import visual_experience_v5_legacy


async def setup(bot):
    await visual_experience_v5_legacy.setup(bot)
    await cosmos_parity.setup(bot)
