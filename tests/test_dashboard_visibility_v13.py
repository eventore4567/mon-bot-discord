from types import SimpleNamespace

from web import dashboard_visibility_guard_v13 as v13


def test_visibility_v13_exposes_growth_renderer_and_browser_guards():
    needle = 'function render(tab=st()?.tab){if(!R[tab])return;syncActive();R[tab]()}'
    fake = SimpleNamespace(
        INDEX_HTML=(
            '<html><head></head><body>'
            '<nav id="navigation" class="nav"></nav><section id="content"></section>'
            '<script id="sentrix-growth-v12-js">'
            + needle
            + '</script></body></html>'
        )
    )

    assert v13.install(fake) is True
    html = fake.INDEX_HTML
    assert 'id="sentrix-dashboard-visibility-v13-css"' in html
    assert 'id="sentrix-dashboard-visibility-v13-js"' in html
    assert 'window.__sentrixGrowthV12Api={render,setTab,ensureNav,TABS};' in html
    assert 'data-sx13-tab' in html
    assert 'CAPTCHA V96 RÉEL' in html
    assert 'verifyPublish' in html


def test_visibility_v13_is_idempotent():
    needle = 'function render(tab=st()?.tab){if(!R[tab])return;syncActive();R[tab]()}'
    fake = SimpleNamespace(
        INDEX_HTML='<html><head></head><body><script id="sentrix-growth-v12-js">'
        + needle
        + '</script></body></html>'
    )
    assert v13.install(fake) is True
    once = fake.INDEX_HTML
    assert v13.install(fake) is True
    assert fake.INDEX_HTML == once
