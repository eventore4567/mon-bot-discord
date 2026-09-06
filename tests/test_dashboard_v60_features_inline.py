from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest
from aiohttp import web


def _prestart_html() -> str:
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    return str(dashboard.INDEX_HTML)


def test_feature_suite_is_a_real_v60_tab_not_an_external_dashboard():
    document = _prestart_html()
    assert 'id="sentrix-v60-features-inline"' in document
    assert 'data-tab="features"' in document
    assert "Fonctions avancées" in document
    assert "/feature-suite?embed=1&guild=" in document
    assert "state.tab==='features'" in document
    assert "styleEmbeddedFeatureSuite" in document
    assert "--accent:#d66f55!important" in document


def test_old_feature_suite_url_redirects_back_to_v60_shell():
    _prestart_html()
    from web import feature_suite_dashboard_v37 as feature_suite

    assert getattr(feature_suite.handle_page, "_sentrix_v60_inline_redirect", False) is True

    request = SimpleNamespace(query={"guild": "123456789"})
    with pytest.raises(web.HTTPFound) as exc:
        asyncio.run(feature_suite.handle_page(request))
    assert exc.value.location == "/app?tab=features&guild=123456789"


def test_feature_suite_embed_path_is_reserved_for_the_v60_iframe():
    document = _prestart_html()
    from web import dashboard_v60_features_inline as inline

    source = inspect.getsource(inline)
    assert 'request.query.get("embed") == "1"' in source
    assert 'X-SentriX-Feature-Suite' in source
    assert 'v60-embedded' in source
    assert "iframe" in document
