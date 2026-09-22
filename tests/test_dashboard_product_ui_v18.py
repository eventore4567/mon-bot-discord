from web import dashboard_product_ui_v18
from web import dashboard_unified_v2
import pytest


@pytest.mark.skip(reason="Couche historique retirée du programme /app (refonte 2026-09, lot 1) : le finalizer sert un programme unique ; suppression de la couche au lot 7.")
def test_v18_patches_native_unified_v2_once():
    html = dashboard_product_ui_v18.patch_html(dashboard_unified_v2.INDEX_HTML)

    assert 'id="sentrix-dashboard-product-ui-v18"' in html
    assert '__sentrixProductUiV18' in html
    assert '["product","Centre avancé","PX"]' in html
    assert 'product:["Centre avancé"' in html
    assert "case'product':await renderProductV18();break;" in html
    assert 'name="sentrix-dashboard-product-build"' in html

    assert dashboard_product_ui_v18.patch_html(html) == html


@pytest.mark.skip(reason="Couche historique retirée du programme /app (refonte 2026-09, lot 1) : le finalizer sert un programme unique ; suppression de la couche au lot 7.")
def test_v18_keeps_single_sidebar_destination():
    html = dashboard_product_ui_v18.patch_html(dashboard_unified_v2.INDEX_HTML)
    assert html.count('["product","Centre avancé","PX"]') == 1
    assert 'Actions staff, automations, membres, audit, templates et accès dashboard.' in html
