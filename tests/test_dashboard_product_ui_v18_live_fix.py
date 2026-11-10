from pathlib import Path

from sentrix_product_update import _DASHBOARD_RECOVERY_JS
from web import dashboard_growth_control_v12
from web import dashboard_live_response_v15
from web import dashboard_product_ui_v18
from web import dashboard_unified_v2
import pytest


def test_v21_recovery_has_no_permanent_browser_polling():
    # Startup retries are finite; healthy pages must not wake up every N seconds forever.
    assert "setInterval(" not in _DASHBOARD_RECOVERY_JS
    assert "MutationObserver" in _DASHBOARD_RECOVERY_JS
    assert 'addEventListener("visibilitychange"' in _DASHBOARD_RECOVERY_JS
    assert 'addEventListener("online"' in _DASHBOARD_RECOVERY_JS
    assert 'addEventListener("pageshow"' in _DASHBOARD_RECOVERY_JS
    assert "sentrix:recovery-needed" in _DASHBOARD_RECOVERY_JS
    assert "[250, 900, 2000, 4500]" in _DASHBOARD_RECOVERY_JS


def test_v21_has_one_boot_level_dashboard_finalizer_in_shared_bootstrap():
    verification = Path("sentrix_verification_v96_finalizer.py").read_text(encoding="utf-8")
    shared = Path("railway_ha_product_boot.py").read_text(encoding="utf-8")
    primary_v8 = Path("railway_ha_product_boot_v8.py").read_text(encoding="utf-8")
    standby_v8 = Path("sentrix_v98_ha_product_boot_v8.py").read_text(encoding="utf-8")

    assert "sentrix_dashboard_finalizer_v7" not in verification
    assert "install_dashboard_v7()" not in verification
    assert shared.count("install_dashboard_v7()") == 1
    assert "_install_v97_dashboard(dashboard_web)" in shared
    assert shared.index("_install_v97_dashboard(dashboard_web)") < shared.index("install_dashboard_v7()")
    assert "install_dashboard_v7" not in primary_v8
    assert "install_dashboard_v7" not in standby_v8
    assert "_finish_with_dashboard_v8" not in primary_v8
    assert "_finish_with_dashboard_v8" not in standby_v8


def test_v21_growth_routes_exist_before_product_boot_captures_build_app():
    primary_v8 = Path("railway_ha_product_boot_v8.py").read_text(encoding="utf-8")
    standby_v8 = Path("sentrix_v98_ha_product_boot_v8.py").read_text(encoding="utf-8")
    growth = Path("web/dashboard_growth_control_v12.py").read_text(encoding="utf-8")

    # Both production entrypoints must install the route-bearing V12 wrapper before importing
    # the shared product bootstrap, which freezes its current dashboard.build_app reference.
    assert primary_v8.index("_growth_v12.install(_dashboard_preboot)") < primary_v8.index(
        "import railway_ha_product_boot as product_boot"
    )
    assert standby_v8.index("_growth_v12.install(_dashboard_preboot)") < standby_v8.index(
        "import sentrix_v98_ha_product_boot as v98_boot"
    )
    assert "product_boot.dashboard_web.build_app._sentrix_growth_v12_routes = True" in primary_v8
    assert "product_boot.dashboard_web.build_app._sentrix_growth_v12_routes = True" in standby_v8

    # These are the real endpoints consumed by the five affected tabs. Automations reuses
    # the reactions endpoint alongside the already-present Ops overview.
    for route in (
        '/api/guilds/{guild_id}/growth/stats',
        '/api/guilds/{guild_id}/growth/invitations',
        '/api/guilds/{guild_id}/growth/webhooks',
        '/api/guilds/{guild_id}/automation/reactions',
    ):
        assert route in growth


def test_growth_pages_are_owned_by_v15_not_by_a_v12_client_router():
    """Historique : V12 rendait lui-même Statistiques/Invitations/Réactions/Automatisations
    via un routeur client (observer sur tout le document, timers). Depuis V15 ces pages sont
    natives ; deux routeurs coexistaient et se marchaient dessus (double « Statistiques »,
    rendu V15 écrasé par un skeleton V12, requêtes dupliquées, skeleton permanent). V12 ne
    conserve que ses routes API et les marqueurs de boot."""
    script = dashboard_growth_control_v12.JS
    style = dashboard_growth_control_v12.CSS
    assert 'id="sentrix-growth-v12-css"' in style
    assert 'id="sentrix-growth-v12-js"' in script
    assert "__sentrixGrowthV12Api" in script
    for retired in ("setInterval(", "MutationObserver", "ensureNav", "/growth/stats", "data-sx12-tab", "sx12-skeleton"):
        assert retired not in script, retired
    assert ".sx12-page" not in style

    native = dashboard_live_response_v15._NATIVE_JS
    for endpoint in ("/growth/stats", "/growth/invitations", "/growth/webhooks", "/automation/reactions", "/ops/overview"):
        assert endpoint in native, endpoint
    # Etats propres : vide explicite, jamais un skeleton laissé en place.
    assert "function v15Empty(" in native
    assert "Aucune donnée disponible." in native
    assert "esc(i.code)" in native


def test_v19_live_metrics_backend_route_exists():
    source = Path("web/dashboard_product_v18.py").read_text(encoding="utf-8")
    assert 'app.router.add_get("/api/guilds/{guild_id}/live/metrics", live_metrics)' in source
    for key in ("members", "commands_24h", "open_tickets", "warnings", "online", "latency_ms", "sanctions_revision"):
        assert f'"{key}"' in source
