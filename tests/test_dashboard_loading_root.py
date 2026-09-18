from pathlib import Path
from types import SimpleNamespace

from web import dashboard_focus_loading_v1 as focus
from web.dashboard_frontend_freeze_v55 import (
    _enhance_unified_product_ux,
    _install_unified_document,
)


FORBIDDEN = (
    "sxLoadingExperience",
    "sxDirectLoader",
    "sentrixLoadingFetch",
    "sentrix-loader-hard-stop-v4",
)


def test_unified_source_has_no_blocking_loader_or_fetch_wrapper():
    html = '<html><head></head><body><script id="sentrix-dashboard-unified-v2"></script></body></html>'
    result = _enhance_unified_product_ux(html)

    assert 'id="sentrix-unified-product-ux-v3"' in result
    assert "confirmNavigation" in result
    assert "syncNavigationA11y" in result
    for marker in FORBIDDEN:
        assert marker not in result


def test_focus_module_only_relocates_server_tools():
    focus._INSTALLED = False
    dashboard = SimpleNamespace(INDEX_HTML="<html><head></head><body></body></html>")

    focus.install(dashboard)

    assert 'id="sentrix-focus-loading-css"' in dashboard.INDEX_HTML
    assert 'id="sentrix-focus-loading-js"' in dashboard.INDEX_HTML
    assert "sxServerToolsLauncher" in dashboard.INDEX_HTML
    assert "sxServerToolsOverlay" in dashboard.INDEX_HTML
    assert "sxDirectLoader" not in dashboard.INDEX_HTML
    assert "window.addEventListener(\"load\"" not in dashboard.INDEX_HTML


def test_final_unified_dashboard_uses_bounded_macos_style_loader():
    dashboard = SimpleNamespace()

    assert _install_unified_document(dashboard)
    html = dashboard.INDEX_HTML

    assert 'id="sentrixProgressHud"' in html
    assert 'role="status"' in html
    assert "function beginBusy" in html
    assert "state.busyTimeout=setTimeout" in html
    assert "function endBusy" in html
    assert "prefers-reduced-motion:reduce" in html
    assert "Chargement du serveur" in html
    assert "Ouverture de la section" in html
    assert "sxLoadingExperience" not in html
    assert "sxDirectLoader" not in html
    assert "sentrixLoadingFetch" not in html


def test_final_unified_dashboard_excludes_background_polls_from_loader():
    dashboard = SimpleNamespace()

    assert _install_unified_document(dashboard)
    html = dashboard.INDEX_HTML

    assert "function isBackgroundRequest" in html
    assert "path==='/health'" in html
    assert "path==='/api/public'" in html
    assert "path==='/live/metrics'" in html
    assert "api('/api/public')" in html
    assert "window.fetch =" not in html


def test_final_unified_dashboard_does_not_clear_content_on_section_render():
    dashboard = SimpleNamespace()

    assert _install_unified_document(dashboard)
    html = dashboard.INDEX_HTML

    assert "$('content').innerHTML=loading();setPage()" not in html
    assert "return withBusy('Ouverture de la section" in html
    assert "case'dm':await window.sentrixRenderDM();break;" in html


def test_railway_entrypoints_do_not_stack_dashboard_finalizers():
    root = Path(__file__).resolve().parents[1]
    primary = (root / "railway_ha_product_boot_v8.py").read_text(encoding="utf-8")
    standby = (root / "sentrix_v98_ha_product_boot_v8.py").read_text(encoding="utf-8")

    for source in (primary, standby):
        assert "dashboard_loader_hard_stop_v4" not in source
        assert "install_dashboard_v7" not in source
        assert "_finish_with_dashboard_v8" not in source
        assert "dashboard_growth_control_v12" in source


def test_shared_boot_keeps_single_final_pass_after_v97():
    root = Path(__file__).resolve().parents[1]
    source = (root / "railway_ha_product_boot.py").read_text(encoding="utf-8")

    v97_call = source.index("_install_v97_dashboard(dashboard_web)")
    final_call = source.index("install_dashboard_v7()", v97_call)
    build_call = source.index("_original_build_app(bot)", final_call)
    assert v97_call < final_call < build_call
