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
    'id="sentrix-dashboard-visibility-v13-css"',
    'id="sentrix-dashboard-visibility-v13-js"',
    'id="sentrix-dashboard-ui-hotfix-v16"',
    'id="sentrix-dashboard-visual-finish-v23"',
    'id="sentrix-dashboard-button-system-v24"',
    'id="sentrix-dashboard-motion-system-v25"',
    'id="sentrix-dashboard-visible-motion-v26"',
    'id="sentrix-dashboard-motion-audio-v27"',
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
    from web import dashboard_visibility_guard_v13
    from web import dashboard_native_bundle_v14
    from web import dashboard_live_response_v15
    from web import dashboard_ui_hotfix_v16
    from web import dashboard_action_hub_v17
    from web import dashboard_product_v18
    from web import dashboard_product_ui_v18_live_fix
    from web import dashboard_visual_finish_v23
    from web import dashboard_button_system_v24
    from web import dashboard_motion_system_v25
    from web import dashboard_visible_motion_v26
    from web import dashboard_motion_audio_v27

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
    if not dashboard_visibility_guard_v13.install(dashboard):
        raise RuntimeError("Dashboard Visibility V13 could not be finalized")
    if not dashboard_native_bundle_v14.install(dashboard):
        raise RuntimeError("Dashboard Native Bundle V14 could not be finalized")

    v15_ok = dashboard_live_response_v15.install(dashboard)
    has_unified_v2_now = 'id="sentrix-dashboard-unified-v2"' in str(
        getattr(dashboard, "INDEX_HTML", "") or ""
    )
    if has_unified_v2_now and not v15_ok:
        raise RuntimeError("Dashboard Live Response V15 could not be finalized")

    v16_ok = dashboard_ui_hotfix_v16.install(dashboard)
    if has_unified_v2_now and not v16_ok:
        raise RuntimeError("Dashboard UI Hotfix V16 could not be finalized")

    try:
        product_v18_ok = bool(dashboard_product_v18.install(dashboard))
    except Exception:
        product_v18_ok = False
        logger.exception("Dashboard Product V18 backend installation failed; stable dashboard remains active.")

    try:
        product_ui_v18_ok = bool(dashboard_product_ui_v18_live_fix.install(dashboard))
    except Exception:
        product_ui_v18_ok = False
        logger.exception("Dashboard Product UI V18 canonical live finalizer failed; stable dashboard remains active.")

    v17_ok = False
    if not product_ui_v18_ok:
        try:
            v17_ok = bool(dashboard_action_hub_v17.install(dashboard))
        except Exception:
            v17_ok = False
            logger.exception("Fallback Action Hub V17 also failed; stable V16 remains authoritative.")
        if has_unified_v2_now and not v17_ok:
            logger.error("Neither V18 nor V17 advanced UI installed; continuing with stable V16.")

    if not dashboard_visual_finish_v23.install(dashboard):
        raise RuntimeError("Dashboard Visual Finish V23 could not be finalized")
    if not dashboard_button_system_v24.install(dashboard):
        raise RuntimeError("Dashboard Button System V24 could not be finalized")
    if not dashboard_motion_system_v25.install(dashboard):
        raise RuntimeError("Dashboard Motion System V25 could not be finalized")
    if not dashboard_visible_motion_v26.install(dashboard):
        raise RuntimeError("Dashboard Visible Motion V26 could not be finalized")

    # V27 targets the actual native/V15 renderer returned to the browser and uses the Web
    # Animations + Web Audio APIs directly so the user sees and hears navigation feedback.
    if not dashboard_motion_audio_v27.install(dashboard):
        raise RuntimeError("Dashboard Motion + Audio V27 could not be finalized")

    final_html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    missing = [marker for marker in REQUIRED_MARKERS if marker not in final_html]
    if missing:
        raise RuntimeError("Final dashboard markers missing: " + ", ".join(missing))
    unified_v2 = 'id="sentrix-dashboard-unified-v2"' in final_html
    runtime_bridge = "__sentrixUnifiedRuntimeV10" in final_html
    growth_v12 = "__sentrixGrowthV12SyntaxGuard" in final_html
    visibility_v13 = "__sentrixDashboardVisibilityV13" in final_html and "__sentrixGrowthV12Api" in final_html
    native_v14 = "__sentrixNativeBundleV14" in final_html
    live_v15 = "__sentrixLiveResponseV15" in final_html
    ui_v16 = "sentrix-dashboard-ui-hotfix-v16" in final_html and "Vérification Discord" in final_html
    actions_v17 = (
        "__sentrixActionHubV17" in final_html
        and "sentrix-dashboard-action-hub-v17" in final_html
        and '["actions","Actions utiles","UT"]' in final_html
    )
    product_ui_v18 = (
        "__sentrixProductUiV18" in final_html
        and "sentrix-dashboard-product-ui-v18" in final_html
        and '["product","Centre avancé","PX"]' in final_html
        and "case'product':await renderProductV18();break;" in final_html
    )
    visual_v23 = 'id="sentrix-dashboard-visual-finish-v23"' in final_html and "__sentrixDashboardVisualFinishV23" in final_html
    buttons_v24 = 'id="sentrix-dashboard-button-system-v24"' in final_html and "__sentrixDashboardButtonSystemV24" in final_html
    motion_v25 = 'id="sentrix-dashboard-motion-system-v25"' in final_html and "__sentrixDashboardMotionSystemV25" in final_html
    visible_motion_v26 = 'id="sentrix-dashboard-visible-motion-v26"' in final_html and "__sentrixDashboardVisibleMotionV26" in final_html
    motion_audio_v27 = 'id="sentrix-dashboard-motion-audio-v27"' in final_html and "__sentrixDashboardMotionAudioV27" in final_html

    if unified_v2 and not runtime_bridge:
        raise RuntimeError("Unified V2 frontend is present but Runtime Bridge V10 is missing")
    if not growth_v12:
        raise RuntimeError("Growth Control V12 assets are present but browser syntax guard is missing")
    if not visibility_v13:
        raise RuntimeError("Visibility V13 assets or Growth V12 renderer bridge are missing")
    if unified_v2 and not native_v14:
        raise RuntimeError("Native Bundle V14 is missing from the canonical V2 browser program")
    if unified_v2 and not live_v15:
        raise RuntimeError("Live Response V15 is missing from the native V2 response program")
    if unified_v2 and not ui_v16:
        raise RuntimeError("UI Hotfix V16 is missing from the browser-visible dashboard")
    if unified_v2 and not product_ui_v18 and not actions_v17:
        logger.error("No advanced UI is present in the startup snapshot; stable V16 remains authoritative.")
    if not visual_v23:
        raise RuntimeError("Visual Finish V23 markers are missing from the final dashboard response")
    if not buttons_v24:
        raise RuntimeError("Button System V24 markers are missing from the final dashboard response")
    if not motion_v25:
        raise RuntimeError("Motion System V25 markers are missing from the final dashboard response")
    if not visible_motion_v26:
        raise RuntimeError("Visible Motion V26 markers are missing from the final dashboard response")
    if not motion_audio_v27:
        raise RuntimeError("Motion + Audio V27 markers are missing from the final dashboard response")

    logger.warning(
        "Dashboard V7 final authority active after legacy freeze: stable V16 + advanced product layer + V23 visual finish + V24 buttons + V25 motion + V26 visible motion + V27 real motion/audio "
        "(html_bytes=%s, real_verify=%s, unified_v2=%s, runtime_bridge=%s, growth_v12=%s, "
        "visibility_v13=%s, native_v14=%s, live_v15=%s, ui_v16=%s, product_v18=%s, product_ui_v18=%s, "
        "v17_fallback=%s, visual_v23=%s, buttons_v24=%s, motion_v25=%s, visible_motion_v26=%s, motion_audio_v27=%s).",
        len(final_html.encode("utf-8")),
        "CAPTCHA V96 RÉEL" in final_html,
        unified_v2,
        runtime_bridge,
        growth_v12,
        visibility_v13,
        native_v14,
        live_v15,
        ui_v16,
        product_v18_ok,
        product_ui_v18_ok and product_ui_v18,
        v17_ok and actions_v17,
        visual_v23,
        buttons_v24,
        motion_v25,
        visible_motion_v26,
        motion_audio_v27,
    )
    return True


__all__ = ["install", "REQUIRED_MARKERS"]
