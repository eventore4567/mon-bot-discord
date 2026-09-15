"""Primary Railway entrypoint with the dashboard authority applied at build time.

The historical V55 frontend can replace dashboard.INDEX_HTML during ha_boot.run(), after the
older V7 finalizer already ran.  This wrapper patches the function that
railway_ha_product_boot calls immediately before aiohttp freezes the application, so V7 wins
at the real last possible moment without changing HA, database, Redis or Discord runtime.

Growth Control V12 is deliberately installed before importing the shared product bootstrap.
The shared bootstrap captures ``dashboard.build_app`` during import; installing V12 after that
capture leaves its HTML visible but drops its aiohttp routes from the live application, which
surfaces as HTTP 404 on Statistics, Invitations, Auto reactions, Automations and Integrations.
"""
from __future__ import annotations

import asyncio
import logging

from web import dashboard as _dashboard_preboot
from web import dashboard_growth_control_v12 as _growth_v12

if not _growth_v12.install(_dashboard_preboot):
    raise RuntimeError("Dashboard Growth Control V12 absent before shared build_app capture.")

import railway_ha_product_boot as product_boot  # noqa: E402
from sentrix_dashboard_finalizer_v7 import install as install_dashboard_v7  # noqa: E402

logger = logging.getLogger("bot.dashboard-final-order-v8")

# V12 is already present in the build_app chain captured by railway_ha_product_boot. Mark the
# final shared guard so the late V7 UI refresh does not wrap a second set of identical routes.
product_boot.dashboard_web.build_app._sentrix_growth_v12_routes = True

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
