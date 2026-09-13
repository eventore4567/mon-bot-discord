from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "x")

from web import dashboard_frontend_freeze_v55 as freeze
from web.dashboard_unified_v2 import INDEX_HTML


def _enhanced() -> str:
    html = freeze._finalize_unified_html(INDEX_HTML)
    return freeze._enhance_unified_product_ux(html)


def test_unified_product_ux_is_injected_once():
    html = _enhanced()
    assert 'id="sentrix-unified-product-ux-v3"' in html
    assert html.count('id="sentrix-unified-product-ux-v3"') == 1
    assert freeze._enhance_unified_product_ux(html) == html


def test_unsaved_changes_guard_server_switch_and_refresh():
    html = _enhanced()
    assert 'hasUnsavedChanges' in html
    assert 'Tu as des modifications non enregistrées.' in html
    assert 'target.closest("[data-guild]")' in html
    assert 'target.closest("#refreshButton")' in html
    assert 'event.stopImmediatePropagation()' in html


def test_palette_has_full_keyboard_navigation():
    html = _enhanced()
    assert 'event.key === "ArrowDown"' in html
    assert 'event.key === "ArrowUp"' in html
    assert 'event.key === "Enter" && current >= 0' in html
    assert 'scrollIntoView?.({block:"nearest"})' in html


def test_navigation_exposes_current_page_and_slash_search_shortcut():
    html = _enhanced()
    assert 'setAttribute("aria-current", "page")' in html
    assert 'removeAttribute("aria-current")' in html
    assert 'event.key !== "/"' in html
    assert 'search.focus()' in html


def test_browser_network_state_is_visible_without_replacing_discord_health():
    html = _enhanced()
    compact = html.replace(' = ', '=')
    assert 'window.addEventListener("offline"' in html
    assert 'text.textContent="Hors ligne"' in compact
    assert 'window.addEventListener("online"' in html
    assert 'text.textContent="Reconnexion…"' in compact
