from __future__ import annotations

import importlib
from types import SimpleNamespace

import web.dashboard_simple_mode as simple_mode


def _module():
    module = importlib.reload(simple_mode)
    dashboard = SimpleNamespace(
        INDEX_HTML='<!doctype html><html><head></head><body><main id="dashboard"></main></body></html>'
    )
    return module, dashboard


def test_v20_simple_mode_is_idempotent_and_keeps_one_surface():
    module, dashboard = _module()

    module.install(dashboard)
    first = dashboard.INDEX_HTML
    module.install(dashboard)

    assert dashboard.INDEX_HTML == first
    assert first.count('id="sentrix-simple-dashboard-css"') == 1
    assert first.count('id="sentrix-simple-dashboard-js"') == 1
    assert "__sentrixSimpleDashboard" in first


def test_v20_personalization_uses_real_destinations_and_browser_storage():
    module, dashboard = _module()
    module.install(dashboard)
    html = dashboard.INDEX_HTML

    assert 'sentrix:dashboard-favorites' in html
    assert 'sentrix:dashboard-recents' in html
    assert 'data-sx-favorite' in html
    assert 'aria-pressed' in html
    assert 'aria-live="polite"' in html

    # Existing, real dashboard destinations only; no placeholder links or fake actions.
    for route in ('/setup-center', '/operations', '/enterprise'):
        assert route in html
    for tab in ('security', 'sanctions', 'welcome', 'tickets', 'ai', 'notifications', 'logs', 'roles'):
        assert f'tab:"{tab}"' in html


def test_v20_removes_permanent_polling_and_uses_event_driven_guild_tracking():
    module, dashboard = _module()
    module.install(dashboard)
    html = dashboard.INDEX_HTML

    assert "MutationObserver" in html
    assert 'serverSelect' in html
    assert 'requestAnimationFrame(checkGuildChange)' in html
    assert "setInterval(" not in html
    assert "600" not in html


def test_v20_search_is_ranked_and_keyboard_accessible():
    module, dashboard = _module()
    module.install(dashboard)
    html = dashboard.INDEX_HTML

    assert "scoreDestination" in html
    assert "lastSearchMatches" in html
    assert 'event.key === "Enter"' in html
    assert 'event.key !== "/"' in html
    assert "Cmd/Ctrl+K" in html
    assert 'aria-label="Rechercher un réglage SentriX"' in html
