from __future__ import annotations

from web.dashboard_frontend_freeze_v55 import (
    _enhance_unified_product_ux,
    _UNIFIED_PRODUCT_UX_MARKER,
)


def _document() -> str:
    return '''<!doctype html><html><head></head><body>
<script id="sentrix-dashboard-unified-v2"></script>
<div id="content"></div>
<div id="runtimeDot"></div><span id="runtimeText"></span>
<div id="navigation"></div><input id="paletteInput"><div id="paletteResults"></div>
<button id="saveButton" class="hidden"></button><button id="refreshButton"></button>
<input id="globalSearch"><div id="paletteBackdrop"></div><button id="mobileMenu"></button>
<div id="mobileOverlay"></div><button id="profileButton"></button>
<script>
async function loadSession(){}
async function loadGuilds(){}
async function selectGuild(value){}
fetch('/api/me');fetch('/api/guilds');
</script>
</body></html>'''


def test_product_ux_is_injected_once_without_loading_overlay():
    html = _enhance_unified_product_ux(_document())
    assert html.count(_UNIFIED_PRODUCT_UX_MARKER) == 1
    for forbidden in (
        'sxLoadingExperience',
        'sentrix-loading-experience-css',
        'sentrixLoadingFetch',
        'LONG_WAIT_MS',
        'RETRY_WAIT_MS',
    ):
        assert forbidden not in html

    html2 = _enhance_unified_product_ux(html)
    assert html2 == html


def test_product_ux_keeps_navigation_safety_and_accessibility():
    html = _enhance_unified_product_ux(_document())
    assert 'confirmNavigation' in html
    assert 'syncNavigationA11y' in html
    assert 'aria-current' in html
    assert 'paletteInput' in html
    assert 'globalSearch' in html


def test_product_ux_does_not_wrap_or_intercept_fetch():
    html = _enhance_unified_product_ux(_document())
    assert 'window.fetch =' not in html
    assert 'sentrixLoadingFetch' not in html
    # Les appels API du document source restent présents : seul le wrapper visuel bloquant disparaît.
    assert "fetch('/api/me')" in html
    assert "fetch('/api/guilds')" in html
