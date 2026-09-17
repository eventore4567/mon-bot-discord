"""Primary Railway entrypoint for the canonical HA product runtime.

Growth Control V12 must be installed before importing the shared bootstrap so its routes are
captured by ``dashboard.build_app``. Everything else, including the single final dashboard
pass after V97, belongs to :mod:`railway_ha_product_boot`.
"""
from __future__ import annotations

import asyncio
import logging

from web import dashboard as _dashboard_preboot
from web import dashboard_growth_control_v12 as _growth_v12

if not _growth_v12.install(_dashboard_preboot):
    raise RuntimeError("Dashboard Growth Control V12 absent before shared build_app capture.")

import railway_ha_product_boot as product_boot  # noqa: E402

logger = logging.getLogger("bot.dashboard-final-order-v8")

# V12 is already present in the build_app chain captured by railway_ha_product_boot.
# Mark the shared guard so the canonical final pass cannot wrap duplicate routes.
product_boot.dashboard_web.build_app._sentrix_growth_v12_routes = True


if __name__ == "__main__":
    try:
        asyncio.run(product_boot.ha_boot.run())
    except KeyboardInterrupt:
        logger.info("Arrêt de SentriX HA V8.")
