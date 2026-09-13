from __future__ import annotations

import re


def _run_prestart():
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    return dashboard


def test_unified_main_document_publishes_no_legacy_secondary_ui():
    dashboard = _run_prestart()
    html = dashboard.INDEX_HTML

    assert 'id="sentrix-dashboard-unified-v2"' in html
    assert 'id="sentrix-unified-runtime-v2"' in html
    assert 'id="sentrix-v60-secondary-theme"' not in html
    assert 'id="sentrix-v60-features-inline"' not in html
    assert 'id="sxFeaturesFrame"' not in html
    assert "sx-features-frame" not in html
    assert "<iframe" not in html.lower()
    assert not re.search(r'<button[^>]+data-tab=["\']features["\']', html, flags=re.I)


def test_unified_navigation_is_grouped_like_one_product_not_separate_sites():
    dashboard = _run_prestart()
    html = dashboard.INDEX_HTML

    for group in ("Général", "Sécurité & modération", "Communauté", "Outils", "Administration"):
        assert group in html

    for tab in ("security", "moderation", "tickets", "config", "access", "dm", "diagnostic"):
        assert re.search(rf'["\']{re.escape(tab)}["\']', html), tab

    # Les anciens centres peuvent rester importables pour compatibilité backend, mais le
    # frontend publié ne doit plus envoyer l'utilisateur vers un deuxième site d'admin.
    for legacy_path in ("/setup-center", "/operations", "/feature-suite", "/community"):
        assert f'href="{legacy_path}"' not in html


def test_old_secondary_theme_helper_is_inert_for_unified_runtime():
    """Le helper historique reste importable, mais unified-v2 ne l'installe plus."""
    from web.dashboard_v60_secondary_theme import apply_secondary_theme

    source = "<!doctype html><html><head></head><body>x</body></html>"
    themed = apply_secondary_theme(source)
    assert 'id="sentrix-v60-secondary-theme"' in themed

    dashboard = _run_prestart()
    assert 'id="sentrix-v60-secondary-theme"' not in dashboard.INDEX_HTML
