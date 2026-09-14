"""Standby Railway V98 entrypoint with dashboard V8 build-time finalization."""
from __future__ import annotations

import asyncio
import logging

import sentrix_v98_ha_product_boot as v98_boot
from sentrix_dashboard_finalizer_v7 import install as install_dashboard_v7

logger = logging.getLogger("bot.dashboard-final-order-v8-standby")
product_boot = v98_boot.product_boot
_original_finish = product_boot._install_embed_dashboard_finish


def _finish_with_dashboard_v8() -> bool:
    embeds_ok = bool(_original_finish())
    dashboard_ok = bool(install_dashboard_v7())
    if not embeds_ok or not dashboard_ok:
        raise RuntimeError(
            f"Dashboard V8 standby finalization failed: embeds={embeds_ok} dashboard={dashboard_ok}"
        )
    logger.warning(
        "Dashboard V8 standby authority applied at actual build_app boundary after legacy V55 freeze."
    )
    return True


_finish_with_dashboard_v8._sentrix_dashboard_v8 = True
product_boot._install_embed_dashboard_finish = _finish_with_dashboard_v8


if __name__ == "__main__":
    try:
        asyncio.run(product_boot.ha_boot.run())
    except KeyboardInterrupt:
        logger.info("Arrêt de SentriX V98 HA V8.")
