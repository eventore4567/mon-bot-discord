from __future__ import annotations


def _run_prestart():
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    return dashboard


def test_v61_redirects_legacy_admin_pages_into_app():
    _run_prestart()

    from web import setup_center
    from web import feature_suite_dashboard_v37
    from web import operations_center
    from web import community_growth

    assert getattr(setup_center.handle_setup_center, "_sentrix_v61_redirect", False)
    assert getattr(feature_suite_dashboard_v37.handle_page, "_sentrix_v61_redirect", False)
    assert getattr(operations_center.handle_operations_page, "_sentrix_v61_redirect", False)
    assert getattr(community_growth.handle_page, "_sentrix_v61_redirect", False)


def test_v61_main_document_contains_no_secondary_theme_or_feature_iframe():
    dashboard = _run_prestart()
    html = dashboard.INDEX_HTML

    assert 'id="sentrix-v61-unified"' in html
    assert 'id="sentrix-v60-secondary-theme"' not in html
    assert 'id="sentrix-v60-features-inline"' not in html
    assert 'data-tab="features"' not in html
    assert "sx-features-frame" not in html


def test_v61_navigation_is_grouped_like_one_product_not_separate_sites():
    dashboard = _run_prestart()
    html = dashboard.INDEX_HTML

    for group in ("Général", "Membres & rôles", "Modération", "Outils", "Configuration"):
        assert group in html
    for tab in ("setup", "games", "design", "status", "access", "dm"):
        assert f'data-tab=\\"{tab}\\"' in html or f'data-tab="{tab}"' in html
    assert "oldMap" in html
    assert "'/setup-center':'setup'" in html
    assert "'/operations':'status'" in html
    assert "'/feature-suite':'setup'" in html


def test_old_secondary_theme_helper_is_inert_for_v61_runtime():
    """Le helper historique peut rester importable, mais V61 ne l'installe plus."""
    from web.dashboard_v60_secondary_theme import apply_secondary_theme

    source = "<!doctype html><html><head></head><body>x</body></html>"
    themed = apply_secondary_theme(source)
    assert 'id="sentrix-v60-secondary-theme"' in themed

    dashboard = _run_prestart()
    assert 'id="sentrix-v60-secondary-theme"' not in dashboard.INDEX_HTML
