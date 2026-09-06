from __future__ import annotations


def _prestart_html() -> str:
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    return str(dashboard.INDEX_HTML)


def test_v61_is_the_final_prestart_frontend():
    document = _prestart_html()
    module = __import__("web.dashboard", fromlist=["dashboard"])
    assert getattr(module, "_sentrix_dashboard_version", None) == "v61-draft-unified-final"
    assert "SENTR<em>IX</em>" in document
    assert "--accent:#d66f55" in document
    assert 'class="server-rail"' in document
    assert 'class="sidebar"' in document
    assert 'id="sentrix-v60-max"' in document
    assert 'id="sentrix-v60-suite"' in document
    assert 'id="sentrix-v60-dm-adapter"' in document
    assert 'id="sentrix-v60-bootguard"' in document
    assert 'id="sentrix-v61-unified"' in document
    # Les boutons V61 sont générés depuis `groups` au runtime : valider les clés du programme,
    # puis le smoke JSDOM valide les vrais boutons DOM après exécution.
    for tab in (
        "overview", "welcome", "roles", "security", "sanctions", "logs", "tickets",
        "notifications", "ai", "embeds", "games", "design", "setup", "access", "dm", "status",
    ):
        assert f'["{tab}",' in document or f"['{tab}'," in document or f'data-tab="{tab}"' in document, tab


def test_v61_removes_the_broken_generic_feature_suite():
    document = _prestart_html()
    from web.dashboard_v61_postfix import _legacy_feature_ui_present

    assert not _legacy_feature_ui_present(document)
    assert 'id="sentrix-v60-features-inline"' not in document
    assert 'id="sxFeaturesFrame"' not in document
    assert 'class="sx-features-shell"' not in document
    assert "L’ancien centre « Fonctions avancées » a été supprimé" in document


def test_v61_keeps_real_api_wiring_inside_one_app():
    document = _prestart_html()
    required = (
        'async function loadSession()',
        'async function loadGuilds()',
        'async function selectGuild(value)',
        '"/api/me"',
        '"/api/guilds"',
        '/settings`,{method:"PUT"',
        '/notifications`,{method:"POST"',
        '/embeds`,{method:"POST"',
        '/diagnostics`',
        '/setup-tools`',
        '/systems`',
        '/games`',
        '/design`',
        '/dm/apercu',
        '/dm/all',
        '/dm/job',
        '/dm/user',
        'Promise.all([loadPublic(),loadSession()])',
    )
    for marker in required:
        assert marker in document, marker


def test_v61_uses_one_draftbot_like_navigation_and_internal_admin_links():
    document = _prestart_html()
    for marker in (
        "Membres & rôles",
        "Modération",
        "Outils",
        "Configuration serveur",
        "Mini-jeux",
        "Design",
        "Statut SentriX",
        "oldMap",
        "'/setup-center':'setup'",
        "'/operations':'status'",
        "'/feature-suite':'setup'",
        "history.replaceState",
        "v61Built",
    ):
        assert marker in document, marker


def test_v60_diagnostics_defines_all_requested_runtime_states():
    from web import dashboard_v60_diagnostics as diagnostics

    assert diagnostics._status("active", "x")["status"] == "ACTIF"
    assert diagnostics._status("inactive", "x")["status"] == "INACTIF"
    assert diagnostics._status("missing", "x")["status"] == "NON CONFIGURÉ"
    assert diagnostics._status("error", "x")["status"] == "ERREUR DE CONFIGURATION"


def test_v60_diagnostics_route_is_bound_before_aiohttp_build():
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    assert dashboard.build_app.__module__ == "web.dashboard_v60_diagnostics"
