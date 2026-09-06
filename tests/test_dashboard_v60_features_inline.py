from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest
from aiohttp import web


def test_feature_suite_frontend_defines_a_real_v60_tab():
    from web import dashboard_v60_features_inline as inline

    document = inline.INLINE_CSS + inline.INLINE_JS
    assert 'id="sentrix-v60-features-inline"' in document
    assert 'data-tab="features"' in document
    assert "Fonctions avancées" in document
    assert "/feature-suite?embed=1&guild=" in document
    assert "state.tab==='features'" in document
    assert "styleEmbeddedFeatureSuite" in document
    assert "--accent:#d66f55!important" in document
    assert "iframe" in document


def test_old_feature_suite_url_redirects_back_to_v60_shell():
    from web import dashboard_v60_features_inline as inline
    from web import feature_suite_dashboard_v37 as feature_suite

    assert inline._install_route_redirect() is True
    assert getattr(feature_suite.handle_page, "_sentrix_v60_inline_redirect", False) is True

    request = SimpleNamespace(query={"guild": "123456789"})
    with pytest.raises(web.HTTPFound) as exc:
        asyncio.run(feature_suite.handle_page(request))
    assert exc.value.location == "/app?tab=features&guild=123456789"


def test_feature_suite_embed_path_is_reserved_for_the_v60_iframe():
    from web import dashboard_v60_features_inline as inline

    source = inspect.getsource(inline)
    assert 'request.query.get("embed") == "1"' in source
    assert 'X-SentriX-Feature-Suite' in source
    assert 'X-Frame-Options' in source
    assert 'v60-embedded' in source


def test_inline_installer_keeps_v60_shell_and_injects_once(monkeypatch):
    from web import dashboard_v60_features_inline as inline

    monkeypatch.setattr(inline, "_INSTALLED", False)
    monkeypatch.setattr(inline, "_install_route_redirect", lambda: True)
    fake = SimpleNamespace(
        INDEX_HTML='<!doctype html><html><head><style>.base{}</style></head><body><nav id="navigation"></nav></body></html>',
        _sentrix_dashboard_version="v60-max-suite",
    )
    assert inline.install(fake) is True
    assert 'id="sentrix-v60-features-inline"' in fake.INDEX_HTML
    assert fake.INDEX_HTML.count('id="sentrix-v60-features-inline"') == 1
    assert inline.install(fake) is True
    assert fake.INDEX_HTML.count('id="sentrix-v60-features-inline"') == 1


def test_final_freeze_guard_reinjects_features_even_if_normal_installer_was_skipped(monkeypatch):
    from web import dashboard_frontend_freeze_v55 as freeze
    from web import dashboard_v60_features_inline as inline

    monkeypatch.setattr(inline, "_install_route_redirect", lambda: True)
    fake = SimpleNamespace(
        INDEX_HTML='<!doctype html><html><head><style>.base{}</style></head><body><nav id="navigation"></nav></body></html>'
    )

    assert freeze._ensure_v60_features_final(fake) is True
    assert 'id="sentrix-v60-features-inline"' in fake.INDEX_HTML
    assert 'data-tab="features"' in fake.INDEX_HTML
    assert "/feature-suite?embed=1&guild=" in fake.INDEX_HTML
    assert len(fake.INDEX_HTML) > 5000
