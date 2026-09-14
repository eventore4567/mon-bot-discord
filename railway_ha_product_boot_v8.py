"""Primary Railway entrypoint with the dashboard authority applied at build time.

The historical V55 frontend can replace dashboard.INDEX_HTML during ha_boot.run(), after the
older V7 finalizer already ran.  This wrapper patches the function that
railway_ha_product_boot calls immediately before aiohttp freezes the application, so V7 wins
at the real last possible moment without changing HA, database, Redis or Discord runtime.
"""
from __future__ import annotations

import asyncio
import logging

import railway_ha_product_boot as product_boot
from sentrix_dashboard_finalizer_v7 import install as install_dashboard_v7

logger = logging.getLogger("bot.dashboard-final-order-v8")

_original_finish = product_boot._install_embed_dashboard_finish


def _finish_with_dashboard_v8() -> bool:
    embeds_ok = bool(_original_finish())
    dashboard_ok = bool(install_dashboard_v7())
    if not embeds_ok or not dashboard_ok:
        raise RuntimeError(
            f"Dashboard V8 finalization failed: embeds={embeds_ok} dashboard={dashboard_ok}"
        )
    logger.warning(
        "Dashboard V8 final authority applied at actual build_app boundary after legacy V55 freeze."
    )
    return True


_finish_with_dashboard_v8._sentrix_dashboard_v8 = True
product_boot._install_embed_dashboard_finish = _finish_with_dashboard_v8


if __name__ == "__main__":
    try:
        asyncio.run(product_boot.ha_boot.run())
    except KeyboardInterrupt:
        logger.info("Arrêt de SentriX HA V8.")
