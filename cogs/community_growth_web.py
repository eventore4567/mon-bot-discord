"""Installe les pages Community Growth avant le démarrage HTTP du dashboard."""
from __future__ import annotations

import logging
from discord.ext import commands

logger = logging.getLogger("bot.community-growth-web")


async def setup(bot: commands.Bot):
    from web import dashboard
    from web import community_growth as community_dashboard
    from web import instance_dashboard_branding

    community_dashboard.install(dashboard)
    instance_dashboard_branding.install(dashboard, community_dashboard)
    logger.info("Community Growth dashboard installé avant le bind HTTP.")
