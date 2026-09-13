from __future__ import annotations


def _prestart_html() -> str:
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    return str(dashboard.INDEX_HTML)


def test_unified_v2_is_the_final_prestart_frontend():
    document = _prestart_html()
    module = __import__("web.dashboard", fromlist=["dashboard"])

    assert getattr(module, "_sentrix_dashboard_version", None) == "unified-v2"
    assert 'id="sentrix-dashboard-unified-v2"' in document
    assert "--blue:#4da3ff" in document
    assert 'class="server-rail"' in document
    assert 'class="sidebar"' in document
    assert 'id="sentrix-product-dashboard-recovery"' in document

    # Les couches UI historiques ne doivent plus composer le document servi.
    for legacy in (
        'id="sentrix-v60-max"',
        'id="sentrix-v60-suite"',
        'id="sentrix-v61-unified"',
        'id="sentrix-v62-dense"',
        'id="sentrix-v63-polish"',
        'id="sentrix-v64-final"',
        'id="sentrix-v60-features-inline"',
        'id="sxFeaturesFrame"',
    ):
        assert legacy not in document

    for tab in (
        "overview", "welcome", "levels", "security", "moderation", "logs",
        "verification", "roles", "economy", "notifications", "tickets", "ai",
        "embeds", "config", "access", "diagnostic",
    ):
        assert f'["{tab}",' in document or f"['{tab}'," in document or f'data-tab="{tab}"' in document, tab


def test_unified_v2_keeps_real_api_wiring_inside_one_app():
    document = _prestart_html()
    required = (
        'async function loadSession()',
        'async function loadGuilds()',
        'async function selectGuild(value)',
        "api('/api/public')",
        "api('/api/me')",
        "api('/api/guilds')",
        '/settings`,{method:',
        '/notifications`,{method:',
        '/embeds`,{method:',
        '/sanctions`',
        '/diagnostics`',
        '/setup-tools`',
        '/v62`',
        "action==='warn'?'clear-warnings':",
    )
    for marker in required:
        assert marker in document, marker


def test_unified_v2_has_complete_primary_navigation():
    document = _prestart_html()
    for marker in (
        "Général",
        "Sécurité & modération",
        "Communauté",
        "Outils",
        "Administration",
        "Vue d’ensemble",
        "Arrivées & départs",
        "Sécurité",
        "Modération",
        "Tickets",
        "Logs",
        "Vérification",
        "Rôles",
        "Niveaux",
        "Économie",
        "Intelligence artificielle",
        "Notifications",
        "Embeds & design",
        "Configuration",
        "Accès & commandes",
        "Diagnostic",
    ):
        assert marker in document, marker


def test_unified_v2_has_mobile_tablet_and_accessibility_contracts():
    document = _prestart_html()
    for marker in (
        "@media(max-width:1180px)",
        "@media(max-width:840px)",
        "@media(max-width:560px)",
        "prefers-reduced-motion:reduce",
        'class="skip" href="#main"',
        'aria-live="polite"',
        'aria-modal="true"',
        "openSidebar()",
        "closeSidebar()",
    ):
        assert marker in document, marker


def test_v60_diagnostics_defines_all_requested_runtime_states():
    from web import dashboard_v60_diagnostics as diagnostics

    assert diagnostics._status("active", "x")["status"] == "ACTIF"
    assert diagnostics._status("inactive", "x")["status"] == "INACTIF"
    assert diagnostics._status("missing", "x")["status"] == "NON CONFIGURÉ"
    assert diagnostics._status("error", "x")["status"] == "ERREUR DE CONFIGURATION"


def test_v62_routes_still_wrap_the_diagnostics_build_before_aiohttp_build():
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    function = getattr(dashboard.build_app, "__func__", dashboard.build_app)
    assert getattr(function, "_sentrix_v62_routes", False)
    assert dashboard.build_app.__module__ == "web.dashboard_v62_dense"
