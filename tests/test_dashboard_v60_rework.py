from __future__ import annotations


def _prestart_html() -> str:
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    return str(dashboard.INDEX_HTML)


def test_v64_is_the_final_prestart_frontend():
    document = _prestart_html()
    module = __import__("web.dashboard", fromlist=["dashboard"])
    assert getattr(module, "_sentrix_dashboard_version", None) == "v64-final"
    assert "SENTR<em>IX</em>" in document
    assert "--accent:#d66f55" in document
    assert "--sx-blue:#4da3ff" in document
    assert "--sx-blue2:#78bdff" in document
    assert "--sx-blue:var(--accent,#d66f55)" not in document
    assert 'class="server-rail"' in document
    assert 'class="sidebar"' in document
    assert 'id="sentrix-v60-max"' in document
    assert 'id="sentrix-v60-suite"' in document
    assert 'id="sentrix-v60-dm-adapter"' in document
    assert 'id="sentrix-v60-bootguard"' in document
    assert 'id="sentrix-v61-unified"' in document
    assert 'id="sentrix-v62-compat"' in document
    assert 'id="sentrix-v62-dense"' in document
    assert 'id="sentrix-v63-polish"' in document
    assert 'id="sentrix-v64-final"' in document
    for tab in (
        "overview", "welcome", "roles", "verification", "security", "sanctions", "logs",
        "tickets", "notifications", "economy", "ai", "embeds", "games", "design", "setup",
        "access", "dm", "status",
    ):
        assert f'["{tab}",' in document or f"['{tab}'," in document or f'data-tab="{tab}"' in document, tab


def test_v64_removes_the_broken_generic_feature_suite():
    document = _prestart_html()
    from web.dashboard_v61_postfix import _legacy_feature_ui_present

    assert not _legacy_feature_ui_present(document)
    assert 'id="sentrix-v60-features-inline"' not in document
    assert 'id="sxFeaturesFrame"' not in document
    assert 'class="sx-features-shell"' not in document
    final_groups = document[document.index("const FINAL_GROUPS"):document.index("let lastSearch", document.index("const FINAL_GROUPS"))]
    assert "Fonctions avancées" not in final_groups
    assert "Messages récurrents" not in final_groups


def test_v64_keeps_real_api_wiring_inside_one_app():
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
        '/v62`',
        '/dm/apercu',
        '/dm/all',
        '/dm/job',
        '/dm/user',
        'Promise.all([loadPublic(),loadSession()])',
    )
    for marker in required:
        assert marker in document, marker


def test_v64_uses_one_draftbot_like_shell_with_sentrix_details():
    document = _prestart_html()
    for marker in (
        "Membres & rôles",
        "Modération",
        "Communauté",
        "Outils",
        "Configuration serveur",
        "Vérification & règlement",
        "Mini-jeux",
        "Design",
        "Statut SentriX",
        "const FINAL_GROUPS",
        "sx-v63-discord",
        "sx-v62-grid",
    ):
        assert marker in document, marker


def test_v64_has_mobile_and_tablet_breakpoints_without_secondary_pages():
    document = _prestart_html()
    for marker in (
        "@media(max-width:1180px)",
        "@media(max-width:820px)",
        "@media(max-width:540px)",
        "width:min(86vw,300px)!important",
        "overflow-x:hidden!important",
        "if(innerWidth<821)$('sidebar')?.classList.remove('open')",
    ):
        assert marker in document, marker


def test_v60_diagnostics_defines_all_requested_runtime_states():
    from web import dashboard_v60_diagnostics as diagnostics

    assert diagnostics._status("active", "x")["status"] == "ACTIF"
    assert diagnostics._status("inactive", "x")["status"] == "INACTIF"
    assert diagnostics._status("missing", "x")["status"] == "NON CONFIGURÉ"
    assert diagnostics._status("error", "x")["status"] == "ERREUR DE CONFIGURATION"


def test_v62_routes_wrap_the_diagnostics_build_before_aiohttp_build():
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    function = getattr(dashboard.build_app, "__func__", dashboard.build_app)
    assert getattr(function, "_sentrix_v62_routes", False)
    assert dashboard.build_app.__module__ == "web.dashboard_v62_dense"
