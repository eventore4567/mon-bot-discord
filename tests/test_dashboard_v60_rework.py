from __future__ import annotations


def _prestart_html() -> str:
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    return str(dashboard.INDEX_HTML)


def test_v60_is_the_final_prestart_frontend():
    document = _prestart_html()
    assert getattr(__import__("web.dashboard", fromlist=["dashboard"]), "_sentrix_dashboard_version", None) == "v60"
    assert "SENTR<em>IX</em>" in document
    assert "DraftBot" not in document
    assert "--accent:#d66f55" in document
    assert 'class="server-rail"' in document
    assert 'class="sidebar"' in document
    assert 'data-tab="welcome"' in document
    assert 'data-tab="roles"' in document
    assert 'data-tab="security"' in document
    assert 'data-tab="sanctions"' in document
    assert 'data-tab="logs"' in document
    assert 'data-tab="tickets"' in document
    assert 'data-tab="notifications"' in document
    assert 'data-tab="ai"' in document
    assert 'data-tab="embeds"' in document


def test_v60_keeps_real_api_wiring():
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
        'Promise.all([loadPublic(),loadSession()])',
    )
    for marker in required:
        assert marker in document, marker
