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
    'id="sentrix-unified-adapter-v9-css"',
    'id="sentrix-unified-adapter-v9-js"',
    'id="sentrix-growth-v12-css"',
    'id="sentrix-growth-v12-js"',
)


def install() -> bool:
    from web import dashboard
    from web import dashboard_control_center
    from web import dashboard_control_center_v3
    from web import dashboard_premium_ui_v4
    from web import dashboard_section_variants_v5
    from web import dashboard_verification_v6
    from web import dashboard_unified_runtime_bridge_v10
    from web import dashboard_unified_adapter_v9
    from web import dashboard_growth_control_v12
    from web import dashboard_growth_control_v12_fix

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
    if not dashboard_unified_runtime_bridge_v10.install(dashboard):
        raise RuntimeError("Unified V2 Runtime Bridge V10 could not be finalized")
    if not dashboard_unified_adapter_v9.install(dashboard):
        raise RuntimeError("Unified V2 Adapter V9 could not be finalized")
    if not dashboard_growth_control_v12.install(dashboard):
        raise RuntimeError("Growth Control V12 could not be finalized")
    if not dashboard_growth_control_v12_fix.install(dashboard):
        raise RuntimeError("Growth Control V12 browser syntax guard failed")

    final_html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    missing = [marker for marker in REQUIRED_MARKERS if marker not in final_html]
    if missing:
        raise RuntimeError("Final dashboard markers missing: " + ", ".join(missing))
    unified_v2 = 'id="sentrix-dashboard-unified-v2"' in final_html
    runtime_bridge = "__sentrixUnifiedRuntimeV10" in final_html
    growth_v12 = "__sentrixGrowthV12SyntaxGuard" in final_html
    if unified_v2 and not runtime_bridge:
        raise RuntimeError("Unified V2 frontend is present but Runtime Bridge V10 is missing")
    if not growth_v12:
        raise RuntimeError("Growth Control V12 assets are present but browser syntax guard is missing")

    logger.warning(
        "Dashboard V7 final authority active after legacy freeze: premium UI, section variants, "
        "control center, Discord verification, unified runtime bridge V10, unified V2 adapter V9 "
        "and Growth Control V12 confirmed (html_bytes=%s, real_verify=%s, unified_v2=%s, runtime_bridge=%s, growth_v12=%s).",
        len(final_html.encode("utf-8")),
        "Vérification Discord réelle" in final_html and "CAPTCHA V96 RÉEL" in final_html,
        unified_v2,
        runtime_bridge,
        growth_v12,
    )
    return True


__all__ = ["install", "REQUIRED_MARKERS"]
