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

    # Barre de progression fine, différée de 350 ms, jamais plein écran.
    assert 'id="progress"' in html
    assert "function progressStart" in html
    assert "function progressEnd" in html
    assert ", 350);" in html
    assert "prefers-reduced-motion:reduce" in html
    assert "loading-screen" not in html
    assert "sxLoadingExperience" not in html
    assert "sxDirectLoader" not in html
    assert "sentrixLoadingFetch" not in html


def test_final_unified_dashboard_excludes_background_polls_from_loader():
    dashboard = SimpleNamespace()

    assert _install_unified_document(dashboard)
    html = dashboard.INDEX_HTML

    assert "function isBackground" in html
    assert "'/api/public', '/health', '/ready'" in html
    assert "endsWith('/live/metrics')" in html
    assert "api('/api/public')" in html
    assert "window.fetch =" not in html


def test_final_unified_dashboard_does_not_clear_content_on_section_render():
    dashboard = SimpleNamespace()

    assert _install_unified_document(dashboard)
    html = dashboard.INDEX_HTML

    # Le contenu précédent reste affiché pendant le chargement d'une page ; le squelette
    # n'apparaît que si la zone est vide (premier serveur).
    assert "if (!content().children.length) content().innerHTML = '<div class=\"skeleton\"" in html
    assert "el.setAttribute('aria-busy', 'true')" in html
    assert "dm: renderDM" in html


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


def test_motion_layers_never_fade_or_blur_whole_content_on_navigation():
    root = Path(__file__).resolve().parents[1]
    v23 = (root / "web/dashboard_visual_finish_v23.py").read_text(encoding="utf-8")
    v25 = (root / "web/dashboard_motion_system_v25.py").read_text(encoding="utf-8")
    v26 = (root / "web/dashboard_visible_motion_v26.py").read_text(encoding="utf-8")

    assert 'content.setAttribute("aria-busy", "true")' not in v23
    assert 'content?.classList.add("sx25-page-out")' not in v25
    assert "opacity:.72" not in v25
    assert "opacity:.25!important" not in v26
    assert "filter:blur(1px)" not in v26
    assert "#sx26Shade{{display:none!important}}" in v26


def test_product_backend_is_installed_before_build_app_is_captured():
    root = Path(__file__).resolve().parents[1]
    source = (root / "railway_ha_product_boot.py").read_text(encoding="utf-8")

    product_install = source.index("_dashboard_product_v18.install(dashboard_web)")
    capture = source.index("_original_build_app = dashboard_web.build_app")
    final_wrapper = source.index("def _build_app_with_final_dashboard")
    assert product_install < capture < final_wrapper
