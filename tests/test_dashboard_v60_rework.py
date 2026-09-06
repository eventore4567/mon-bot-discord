from __future__ import annotations


def _prestart_html() -> str:
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    return str(dashboard.INDEX_HTML)


def test_v60_max_is_the_final_prestart_frontend():
    document = _prestart_html()
    module = __import__("web.dashboard", fromlist=["dashboard"])
    assert getattr(module, "_sentrix_dashboard_version", None) == "v60-max"
    assert "SENTR<em>IX</em>" in document
    assert "DraftBot" not in document
    assert "--accent:#d66f55" in document
    assert 'class="server-rail"' in document
    assert 'class="sidebar"' in document
    assert 'id="sentrix-v60-max"' in document
    for tab in (
        "welcome", "roles", "security", "sanctions", "logs", "tickets",
        "notifications", "ai", "embeds",
    ):
        assert f'data-tab="{tab}"' in document


def test_v60_max_keeps_real_api_wiring():
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
        '/sanctions/${encodeURIComponent(userId)}/${encodeURIComponent(action)}`',
        'Promise.all([loadPublic(),loadSession()])',
    )
    for marker in required:
        assert marker in document, marker


def test_v60_max_exposes_the_advanced_requested_controls():
    document = _prestart_html()
    markers = (
        "Vue d’ensemble",
        "Rechercher une fonction",
        "welcome_image_url",
        "warn_ban_threshold",
        "verification_channel",
        "giveaway_channel",
        "partner_channel",
        "stats_channel",
        "afk_channel",
        "notifImage",
        "embedAuthorName",
        "embedThumbnail",
        "embedFooter",
        "sxAddEmbedField",
        "clear-warnings",
        "Ctrl/⌘ + S",
    )
    for marker in markers:
        assert marker in document, marker
