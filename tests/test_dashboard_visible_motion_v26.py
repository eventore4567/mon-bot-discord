from types import SimpleNamespace

from web import dashboard_visible_motion_v26 as v26


def _dashboard():
    return SimpleNamespace(
        INDEX_HTML='<!doctype html><html><head></head><body><main id="content"><h1>Dashboard</h1></main></body></html>'
    )


def test_v26_installs_once_and_preserves_dashboard_content():
    dashboard = _dashboard()
    assert v26.install(dashboard) is True
    html = dashboard.INDEX_HTML
    assert html.count('id="sentrix-dashboard-visible-motion-v26"') == 1
    assert html.count('id="sentrix-dashboard-visible-motion-v26-js"') == 1
    assert "__sentrixDashboardVisibleMotionV26" in html
    assert "<h1>Dashboard</h1>" in html

    first = dashboard.INDEX_HTML
    assert v26.install(dashboard) is True
    assert dashboard.INDEX_HTML == first


def test_v26_is_clearly_visible_event_driven_and_accessible():
    style = v26.STYLE
    script = v26.SCRIPT

    assert "setInterval(" not in script
    assert "MutationObserver" in script
    assert "requestAnimationFrame" in script
    assert "aria-busy" in script
    assert "pointerdown" in script
    assert "animationend" in script
    assert "sentrix:live" in script
    assert "1200" in script

    assert "#sx26Progress" in style
    assert "height:4px" in style
    assert "#sx26Shade" in style
    assert "translateY(18px)" in style
    assert "scale(.988)" in style
    assert "sx26-ripple" in style
    assert "scale(.955)" in style
    assert "sx26-stagger" in style
    assert "sx26-toast-in" in style
    assert "sx26-dialog-in" in style
    assert "@media(prefers-reduced-motion:reduce)" in style


def test_v26_runs_after_v25_as_final_presentation_authority():
    source = open("sentrix_dashboard_finalizer_v7.py", encoding="utf-8").read()
    assert "from web import dashboard_visible_motion_v26" in source
    assert "dashboard_visible_motion_v26.install(dashboard)" in source
    assert source.index("dashboard_motion_system_v25.install(dashboard)") < source.index(
        "dashboard_visible_motion_v26.install(dashboard)"
    )
    assert 'id="sentrix-dashboard-visible-motion-v26"' in source
    assert "visible_motion_v26" in source
