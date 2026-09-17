"""Standby Railway V98 entrypoint with dashboard V8 build-time finalization.

Growth Control V12 is installed before importing the shared V98/product bootstrap so its
route-bearing build_app wrapper is part of the function chain captured for the live aiohttp
application. The late V7 pass remains responsible for refreshing the final UI after V55.
"""
from __future__ import annotations

import asyncio
import logging

from web import dashboard as _dashboard_preboot
from web import dashboard_growth_control_v12 as _growth_v12

if not _growth_v12.install(_dashboard_preboot):
    raise RuntimeError("Dashboard Growth Control V12 absent before standby build_app capture.")

import sentrix_v98_ha_product_boot as v98_boot  # noqa: E402
from sentrix_dashboard_finalizer_v7 import install as install_dashboard_v7  # noqa: E402
from web.dashboard_loader_hard_stop_v4 import install as install_loader_hard_stop_v4  # noqa: E402

logger = logging.getLogger("bot.dashboard-final-order-v8-standby")
product_boot = v98_boot.product_boot

# The shared guard contains the V12 route wrapper captured above. Keep the V12 marker on the
# exposed guard so the final UI pass cannot add a duplicate copy of the same aiohttp routes.
product_boot.dashboard_web.build_app._sentrix_growth_v12_routes = True

_original_finish = product_boot._install_embed_dashboard_finish


def _finish_with_dashboard_v8() -> bool:
    embeds_ok = bool(_original_finish())
    dashboard_ok = bool(install_dashboard_v7())
    loader_ok = bool(install_loader_hard_stop_v4(product_boot.dashboard_web))
    if not embeds_ok or not dashboard_ok or not loader_ok:
        raise RuntimeError(
            "Dashboard V8 standby finalization failed: "
            f"embeds={embeds_ok} dashboard={dashboard_ok} loader_hard_stop={loader_ok}"
        )
    logger.warning(
        "Dashboard V8 standby authority applied at actual build_app boundary after legacy V55 freeze; "
        "blocking loaders disabled by V4."
    )
    return True


_finish_with_dashboard_v8._sentrix_dashboard_v8 = True
product_boot._install_embed_dashboard_finish = _finish_with_dashboard_v8


if __name__ == "__main__":
    try:
        asyncio.run(product_boot.ha_boot.run())
    except KeyboardInterrupt:
        logger.info("Arrêt de SentriX V98 HA V8.")
