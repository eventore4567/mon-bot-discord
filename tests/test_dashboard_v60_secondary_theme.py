from __future__ import annotations


def _full_documents(module):
    docs = []
    for name, value in vars(module).items():
        if not isinstance(value, str):
            continue
        lower = value.lstrip().lower()
        if (lower.startswith("<!doctype html") or lower.startswith("<html")) and "</head>" in value and "<body" in lower:
            docs.append((name, value))
    return docs


def _run_prestart():
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    return dashboard


def test_secondary_admin_pages_receive_the_same_v60_theme():
    dashboard = _run_prestart()

    from web import setup_center
    from web import embed_center
    from web import owner_server_manager
    from web import operations_center
    from web import community_growth
    from web import engagement_hub
    from web import feature_suite_dashboard_v37

    required_modules = (
        setup_center,
        embed_center,
        owner_server_manager,
        operations_center,
        community_growth,
        engagement_hub,
        feature_suite_dashboard_v37,
    )

    for module in required_modules:
        docs = _full_documents(module)
        assert docs, f"{module.__name__} ne possède plus de document HTML autonome"
        for name, document in docs:
            assert 'id="sentrix-v60-secondary-theme"' in document, f"{module.__name__}.{name} n'est pas harmonisé"
            assert "--sx-accent:#d66f55" in document
            assert "--sx-content:#383c42" in document
            assert "--sx-card:#34383e" in document
            assert "border-radius:6px!important" in document

    # L'accueil principal possède déjà son propre thème V60 et ne doit jamais recevoir la
    # feuille destinée aux centres autonomes.
    assert 'id="sentrix-v60-secondary-theme"' not in dashboard.INDEX_HTML
    assert "--accent:#d66f55" in dashboard.INDEX_HTML


def test_secondary_theme_is_idempotent_and_only_accepts_full_documents():
    from web.dashboard_v60_secondary_theme import apply_secondary_theme

    source = "<!doctype html><html><head><style>body{background:purple}</style></head><body><main>x</main></body></html>"
    once = apply_secondary_theme(source)
    twice = apply_secondary_theme(once)
    assert once == twice
    assert once.count('id="sentrix-v60-secondary-theme"') == 1
    assert apply_secondary_theme("<div>fragment</div>") == "<div>fragment</div>"


def test_setup_center_old_purple_rework_is_visually_overridden_last():
    _run_prestart()

    from web import setup_center

    html = setup_center.SETUP_CENTER_HTML
    old_rework = html.find('id="sentrix-setup-semi2d-rework"')
    unified = html.find('id="sentrix-v60-secondary-theme"')
    assert old_rework >= 0, "le rework Setup attendu a disparu"
    assert unified > old_rework, "le thème V60 doit arriver après l'ancien thème violet"
    assert ".tab.active,.tabs .tab.active" in html
    assert "color:var(--sx-accent2)!important" in html
    assert "background:var(--sx-card)!important" in html
