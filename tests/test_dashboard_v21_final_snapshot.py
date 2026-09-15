from __future__ import annotations

from types import SimpleNamespace


def _compose_final_unified_html() -> str:
    # Importing web reproduces the real module installation order used by Railway before
    # product pre-start. V55 must then be able to rebuild one unified document without
    # losing the V19/V20 product UX that was installed earlier.
    import web  # noqa: F401
    from web import dashboard_frontend_freeze_v55 as freeze

    dashboard = SimpleNamespace(INDEX_HTML="", _sentrix_dashboard_version="")
    assert freeze._install_unified_document(dashboard) is True
    return str(dashboard.INDEX_HTML)


def test_v21_final_v55_snapshot_keeps_v19_and_v20_once():
    html = _compose_final_unified_html()

    assert html.count('id="sentrix-dashboard-unified-v2"') == 1
    assert html.count('id="sentrix-simple-dashboard-css"') == 1
    assert html.count('id="sentrix-simple-dashboard-js"') == 1
    assert html.count('id="sentrix-dashboard-v19-polish"') == 1
    assert html.count('id="sentrix-dashboard-v19-polish-js"') == 1
    assert html.count('id="sentrix-product-dashboard-recovery"') == 1

    # V20 personalization must exist in the exact document V55 is about to freeze.
    assert "sentrix:dashboard-favorites" in html
    assert "sentrix:dashboard-recents" in html
    assert "scoreDestination" in html
    assert "MutationObserver" in html
    assert "Cmd/Ctrl+K" in html

    # V18/V19 product center and live metrics must survive the V55 rebuild too.
    assert '["product","Centre avancé","PX"]' in html
    assert "case'product':await renderProductV18();break;" in html
    assert 'id="paletteBackdrop"' in html
    assert '"/giveaways", "Giveaways"' in html
    assert "new EventSource(`/api/guilds/${encodeURIComponent(guildId)}/live/stream`" in html


def test_v21_final_snapshot_has_no_legacy_duplicate_surface_or_recovery_loop():
    html = _compose_final_unified_html()

    assert 'id="sentrix-v60-features-inline"' not in html
    assert 'id="sxFeaturesFrame"' not in html
    assert "setInterval(() => recoverProductUi(), 7000)" not in html
    assert "sx19-command-overlay" not in html
    assert "sx19-command-hint" not in html


def test_v21_v55_freeze_is_idempotent_for_the_composed_document():
    from web import dashboard_frontend_freeze_v55 as freeze

    html = _compose_final_unified_html()

    async def original(_request):
        return None

    dashboard = SimpleNamespace(
        INDEX_HTML=html,
        handle_index=original,
        _sentrix_dashboard_version="unified-v2",
    )
    assert freeze.install(dashboard) is True
    first_snapshot = dashboard._sentrix_frontend_snapshot_v55
    first_sha = dashboard._sentrix_frontend_snapshot_sha_v55

    assert freeze.install(dashboard) is True
    assert dashboard._sentrix_frontend_snapshot_v55 == first_snapshot
    assert dashboard._sentrix_frontend_snapshot_sha_v55 == first_sha
    assert dashboard.handle_index._sentrix_frontend_freeze_v55 is True
