from web import dashboard_live_response_v15
from web import dashboard_product_ui_v18
from web import dashboard_product_ui_v18_live_fix
from web import dashboard_product_ui_v19
from web import dashboard_ui_hotfix_v16
from web import dashboard_unified_v2


def _product_v18_html():
    html = dashboard_live_response_v15.patch_html(dashboard_unified_v2.INDEX_HTML)
    html = dashboard_ui_hotfix_v16.patch_html(html)
    html = dashboard_product_ui_v18_live_fix.patch_html(html)
    return html


def test_v19_extends_real_v18_center_without_new_sidebar_page():
    base = _product_v18_html()
    assert dashboard_product_ui_v18.JS_MARKER in base
    assert '["product","Centre avancé","PX"]' in base

    html = dashboard_product_ui_v19.patch_html(base)
    assert dashboard_product_ui_v19.JS_MARKER in html
    assert dashboard_product_ui_v19.MARKER in html
    assert "Actions groupées" in html
    assert "Onboarding" in html
    assert "p19RenderLive" in html
    assert "p19RenderBulk" in html
    assert "p19RenderOnboarding" in html
    assert html.count('["product","Centre avancé","PX"]') == 1


def test_v19_is_idempotent_and_keeps_mobile_rules():
    html = dashboard_product_ui_v19.patch_html(_product_v18_html())
    assert dashboard_product_ui_v19.patch_html(html) == html
    assert "@media(max-width:720px)" in html
    assert ".p19-bulkbar" in html
