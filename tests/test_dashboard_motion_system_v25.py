from types import SimpleNamespace

from web import dashboard_motion_system_v25 as v25


def _dashboard():
    return SimpleNamespace(
        INDEX_HTML='<!doctype html><html><head></head><body><main id="content"><h1>Dashboard</h1></main></body></html>'
    )


def test_v25_installs_once_without_replacing_real_dashboard_content():
    dashboard = _dashboard()
    assert v25.install(dashboard) is True
    html = dashboard.INDEX_HTML
    assert html.count('id="sentrix-dashboard-motion-system-v25"') == 1
    assert html.count('id="sentrix-dashboard-motion-system-v25-js"') == 1
    assert "__sentrixDashboardMotionSystemV25" in html
    assert "<h1>Dashboard</h1>" in html

    first = dashboard.INDEX_HTML
    assert v25.install(dashboard) is True
    assert dashboard.INDEX_HTML == first


def test_v25_is_event_driven_and_covers_premium_motion_states():
    style = v25.STYLE
    script = v25.SCRIPT

    assert "setInterval(" not in script
    assert "MutationObserver" in script
    assert "requestAnimationFrame" in script
    assert "aria-busy" in script
    assert "pointerdown" in script
    assert "animationend" in script
    # Le tick temps réel (sentrix:live) ne rejoue plus aucune animation : c'était un
    # clignotement périodique des badges toutes les 20 s.
    assert "sentrix:live" not in script

    # Barre de progression en haut retirée (quatre couches en empilaient une chacune).
    assert "#sx25Progress" not in style
    assert 'String(Math.min(index, 8))' in script
    assert "sx25-page-in" in style
    assert "sx25-ripple" in style
    assert "sx25-card-in" in style
    assert "sx25-row-in" in style
    assert "sx25-toast-in" in style
    assert "sx25-dialog-in" in style
    assert "sx25-shimmer" in style
    assert "sx25-selected" in style
    assert "@media(prefers-reduced-motion:reduce)" in style


def test_v25_runs_after_v23_and_v24_in_final_authority():
    source = open("sentrix_dashboard_finalizer_v7.py", encoding="utf-8").read()
    assert "from web import dashboard_motion_system_v25" in source
    assert "dashboard_motion_system_v25.install(dashboard)" in source
    assert source.index("dashboard_visual_finish_v23.install(dashboard)") < source.index(
        "dashboard_button_system_v24.install(dashboard)"
    ) < source.index("dashboard_motion_system_v25.install(dashboard)")
    assert 'id="sentrix-dashboard-motion-system-v25"' in source
    assert "motion_v25" in source
