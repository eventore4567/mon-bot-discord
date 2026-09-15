from web import dashboard_live_response_v15
from web import dashboard_product_ui_v18
from web import dashboard_product_ui_v18_live_fix
from web import dashboard_ui_hotfix_v16
from web import dashboard_unified_v2


def _live_v16_html():
    html = dashboard_live_response_v15.patch_html(dashboard_unified_v2.INDEX_HTML)
    return dashboard_ui_hotfix_v16.patch_html(html)


def test_v18_live_fix_patches_real_v15_v16_shape():
    live_html = _live_v16_html()

    # This is the production shape that made the original V18 exact anchors miss.
    assert '["staffactivity","Activité staff","AS"]' in live_html
    assert "case'staffactivity':await renderStaffV15();break;" in live_html

    patched = dashboard_product_ui_v18_live_fix.patch_html(live_html)

    assert '["product","Centre avancé","PX"]' in patched
    assert patched.count('["product","Centre avancé","PX"]') == 1
    assert 'product:["Centre avancé"' in patched
    assert dashboard_product_ui_v18.JS_MARKER in patched
    assert dashboard_product_ui_v18.MARKER in patched
    assert "case'product':await renderProductV18();break;" in patched
    assert 'name="sentrix-dashboard-product-ui-v18-live-fix"' in patched

    # V19 reuses the Unified V2 palette rather than shipping a competing Cmd/Ctrl+K UI.
    assert dashboard_product_ui_v18_live_fix.POLISH_MARKER in patched
    assert dashboard_product_ui_v18_live_fix.POLISH_JS_MARKER in patched
    assert 'id="paletteBackdrop"' in patched
    assert '"/giveaways", "Giveaways"' in patched
    assert '"/embed-builder", "Créateur d’embeds"' in patched
    assert "sx19-command-overlay" not in patched
    assert "sx19-command-hint" not in patched


def test_v18_live_fix_is_idempotent_on_live_shape():
    patched = dashboard_product_ui_v18_live_fix.patch_html(_live_v16_html())
    assert dashboard_product_ui_v18_live_fix.patch_html(patched) == patched
    assert patched.count(f'id="{dashboard_product_ui_v18_live_fix.POLISH_MARKER}"') == 1
    assert patched.count('id="sentrix-dashboard-v19-polish-js"') == 1
