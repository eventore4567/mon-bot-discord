"""Final dashboard authority after all historical Railway layers are imported.

Several legacy dashboard layers replace INDEX_HTML late during bootstrap. The operations and
premium layers were previously installed too early, so production could deploy successfully
while still serving the old visual surface. This finalizer runs after railway_ha_boot import
and immediately before aiohttp build wiring.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-finalizer-v7")

REQUIRED_MARKERS = (
    'id="sentrix-control-center-css"',
    'id="sentrix-control-center-js"',
    'id="sentrix-control-center-v3-js"',
    'id="sentrix-premium-ui-v4-css"',
    'id="sentrix-premium-ui-v4-js"',
    'id="sentrix-section-variants-v5-css"',
    'id="sentrix-section-variants-v5-js"',
    'id="sentrix-dashboard-verification-v6-css"',
    'id="sentrix-dashboard-verification-v6-js"',
)


def install() -> bool:
    from web import dashboard
    from web import dashboard_control_center
    from web import dashboard_control_center_v3
    from web import dashboard_premium_ui_v4
    from web import dashboard_section_variants_v5
    from web import dashboard_verification_v6

    # dashboard_control_center historically keeps a module-global install flag. If a later
    # compatibility layer replaced INDEX_HTML, that flag no longer proves its assets exist.
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if (
        'id="sentrix-control-center-css"' not in html
        or 'id="sentrix-control-center-js"' not in html
    ):
        dashboard_control_center._INSTALLED = False
    dashboard_control_center.install(dashboard)

    if not dashboard_control_center_v3.install(dashboard):
        raise RuntimeError("Control Center V3 could not be finalized")
    if not dashboard_premium_ui_v4.install(dashboard):
        raise RuntimeError("Premium UI V4 could not be finalized")
    if not dashboard_section_variants_v5.install(dashboard):
        raise RuntimeError("Section Variants V5 could not be finalized")
    if not dashboard_verification_v6.install(dashboard):
        raise RuntimeError("Discord Verification V6 could not be finalized")

    final_html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    missing = [marker for marker in REQUIRED_MARKERS if marker not in final_html]
    if missing:
        raise RuntimeError("Final dashboard markers missing: " + ", ".join(missing))

    logger.warning(
        "Dashboard V7 final authority active after legacy freeze: premium UI, section variants, control center and Discord verification confirmed."
    )
    return True


__all__ = ["install", "REQUIRED_MARKERS"]
