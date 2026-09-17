"""Standby Railway entrypoint for the shared HA product runtime.

Growth Control V12 is installed before importing the shared bootstrap so its aiohttp routes
are captured. The shared product bootstrap owns the single final dashboard pass after V97;
this entrypoint no longer adds another finalizer or loader patch on top.
"""
from __future__ import annotations

import asyncio
import logging

from web import dashboard as _dashboard_preboot
from web import dashboard_growth_control_v12 as _growth_v12

if not _growth_v12.install(_dashboard_preboot):
    raise RuntimeError("Dashboard Growth Control V12 absent before standby build_app capture.")

import sentrix_v98_ha_product_boot as v98_boot  # noqa: E402

logger = logging.getLogger("bot.dashboard-final-order-v8-standby")
product_boot = v98_boot.product_boot

# The shared guard contains the V12 route wrapper captured above. Keep the marker on the
# exposed guard so the canonical final pass cannot add duplicate routes.
product_boot.dashboard_web.build_app._sentrix_growth_v12_routes = True


if __name__ == "__main__":
    try:
        asyncio.run(product_boot.ha_boot.run())
    except KeyboardInterrupt:
        logger.info("Arrêt de SentriX V98 HA V8.")
