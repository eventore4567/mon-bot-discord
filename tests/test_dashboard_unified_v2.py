from types import SimpleNamespace

from web import dashboard_frontend_freeze_v55 as freeze
from web import dashboard_unified_v2 as unified


def test_unified_dashboard_is_single_frontend_document():
    html = unified.INDEX_HTML

    assert 'id="sentrix-dashboard-unified-v2"' in html
    assert 'id="sentrix-v64-final"' not in html
    assert 'id="sentrix-v60-features-inline"' not in html
    assert 'id="sxFeaturesFrame"' not in html

    # Le runtime du dashboard ne doit pas être une simple maquette : il consomme les
    # endpoints produit réels et contient ses états de navigation/chargement/erreur.
    for marker in (
        'async function loadSession()',
        'async function loadGuilds()',
        'async function selectGuild(value)',
        "'/api/public'",
        "'/api/me'",
        "'/api/guilds'",
        '/diagnostics',
        '/v62',
        '/setup-tools',
        '/notifications',
        '/embeds',
        '/sanctions',
        'class="skeleton"',
        'class="error-state"',
        'class="empty"',
    ):
        assert marker in html


def test_unified_dashboard_accessibility_and_responsive_contract():
    html = unified.INDEX_HTML

    for marker in (
        'class="skip" href="#main"',
        'aria-live="polite"',
        'aria-modal="true"',
        'prefers-reduced-motion:reduce',
        '@media (max-width:900px)',
        '⌘K',
    ):
        assert marker in html


def test_finalizer_uses_real_sanction_route_and_blocks_legacy_recovery_injection():
    source = unified.INDEX_HTML
    # La route réelle est écrite à la source : le finalizer n'a plus rien à corriger.
    assert "'clear-warnings'" in source
    assert "'clearwarnings'" not in source
    assert source.count('id="sentrix-product-dashboard-recovery"') == 1
    assert freeze._finalize_unified_html(source) == source


def test_freeze_accepts_finalized_unified_snapshot():
    async def old_handle_index(_request):
        return None

    dashboard = SimpleNamespace(
        INDEX_HTML=freeze._finalize_unified_html(unified.INDEX_HTML),
        handle_index=old_handle_index,
        _sentrix_dashboard_version="unified-v2",
    )

    assert freeze.install(dashboard) is True
    assert getattr(dashboard.handle_index, "_sentrix_frontend_freeze_v55", False) is True
    assert dashboard._sentrix_frontend_snapshot_sha_v55
    assert 'id="sentrix-v60-features-inline"' not in dashboard._sentrix_frontend_snapshot_v55
