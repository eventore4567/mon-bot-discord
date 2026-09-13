from __future__ import annotations

from web.dashboard_frontend_freeze_v55 import (
    _enhance_unified_product_ux,
    _LOADING_UX_CSS_MARKER,
    _LOADING_UX_HTML_MARKER,
    _UNIFIED_PRODUCT_UX_MARKER,
)


def _document() -> str:
    return '''<!doctype html><html><head></head><body>
<div id="sentrix-dashboard-unified-v2"></div>
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


def test_loading_experience_is_injected_once():
    html = _enhance_unified_product_ux(_document())
    assert html.count(_LOADING_UX_CSS_MARKER) == 1
    assert html.count(_LOADING_UX_HTML_MARKER) == 1
    assert html.count(_UNIFIED_PRODUCT_UX_MARKER) == 1

    html2 = _enhance_unified_product_ux(html)
    assert html2 == html


def test_loading_experience_has_real_stages_and_retry():
    html = _enhance_unified_product_ux(_document())
    for label in (
        'Vérification de ta session',
        'Synchronisation avec Discord',
        'Chargement de tes serveurs',
        'Préparation du serveur',
        'Ça prend plus longtemps que prévu',
        'Réessayer',
        'Hors ligne',
    ):
        assert label in html
    assert 'aria-live="polite"' in html
    assert 'prefers-reduced-motion:reduce' in html


def test_loading_experience_does_not_use_fake_percentages():
    html = _enhance_unified_product_ux(_document())
    assert 'fake-progress' not in html
    assert 'data-percent' not in html


def test_loader_tracks_dashboard_api_calls_and_timeouts():
    html = _enhance_unified_product_ux(_document())
    assert 'window.fetch = async function sentrixLoadingFetch' in html
    assert 'url.includes("/api/me")' in html
    assert 'url.includes("/api/guilds")' in html
    assert 'LONG_WAIT_MS' in html
    assert 'RETRY_WAIT_MS' in html
    assert 'AbortError' in html
