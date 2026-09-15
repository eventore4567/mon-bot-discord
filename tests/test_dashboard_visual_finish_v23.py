from types import SimpleNamespace

from web import dashboard_visual_finish_v23 as v23


def _dashboard():
    return SimpleNamespace(
        INDEX_HTML='<!doctype html><html><head></head><body><main id="content"><h1>Dashboard</h1></main></body></html>'
    )


def test_v23_installs_once_and_keeps_real_content_authoritative():
    dashboard = _dashboard()
    assert v23.install(dashboard) is True
    html = dashboard.INDEX_HTML
    assert html.count('id="sentrix-dashboard-visual-finish-v23"') == 1
    assert html.count('id="sentrix-dashboard-visual-finish-v23-js"') == 1
    assert "__sentrixDashboardVisualFinishV23" in html
    assert "<h1>Dashboard</h1>" in html

    first = dashboard.INDEX_HTML
    assert v23.install(dashboard) is True
    assert dashboard.INDEX_HTML == first


def test_v23_is_event_driven_accessible_and_mobile_hardened():
    style = v23.STYLE
    script = v23.SCRIPT

    assert "setInterval(" not in script
    assert "MutationObserver" in script
    assert 'addEventListener("online"' in script
    assert 'addEventListener("offline"' in script
    assert 'addEventListener("pageshow"' in script
    assert 'addEventListener("sentrix:live"' in script
    assert 'setAttribute("aria-busy", "true")' in script
    assert 'setAttribute("aria-current", "page")' in script
    assert 'setAttribute("aria-live", "polite")' in script

    assert "@media(max-width:760px)" in style
    assert "@media(max-width:520px)" in style
    assert "@media(prefers-contrast:more)" in style
    assert "@media(prefers-reduced-motion:reduce)" in style
    assert "@media(forced-colors:active)" in style
    assert ".sx12-flow-steps" in style
    assert ".sx12-invite-grid" in style
    assert ".p18-table" in style
    assert "touch-action:manipulation" in style


def test_v23_runs_after_product_ui_in_final_authority():
    source = open("sentrix_dashboard_finalizer_v7.py", encoding="utf-8").read()
    assert "from web import dashboard_visual_finish_v23" in source
    assert "dashboard_visual_finish_v23.install(dashboard)" in source
    assert source.index("dashboard_product_ui_v18_live_fix.install(dashboard)") < source.index(
        "dashboard_visual_finish_v23.install(dashboard)"
    )
    assert 'id="sentrix-dashboard-visual-finish-v23"' in source
    assert "visual_v23" in source
