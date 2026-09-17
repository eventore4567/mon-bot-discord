from types import SimpleNamespace

from web import dashboard_visibility_guard_v13 as v13

_V12_SCRIPT = (
    '<script id="sentrix-growth-v12-js">'
    'window.__sentrixGrowthV12Api={retired:true,renderer:"v15-native"};'
    '</script>'
)


def _fake(with_api_marker: bool = True):
    return SimpleNamespace(
        INDEX_HTML=(
            '<html><head></head><body>'
            '<nav id="navigation" class="nav"></nav><section id="content"></section>'
            + (_V12_SCRIPT if with_api_marker else '<script id="sentrix-growth-v12-js"></script>')
            + '</body></html>'
        )
    )


def test_visibility_v13_keeps_only_the_captcha_guard():
    """V13 relançait le renderer V12 (ensureCurrent) sur chaque mutation de #content et
    toutes les 650 ms, écrasant le rendu natif V15 par un skeleton et dupliquant les
    requêtes. Il ne reste que la mise en évidence du contrôle CAPTCHA V96."""
    fake = _fake()
    assert v13.install(fake) is True
    html = fake.INDEX_HTML
    assert 'id="sentrix-dashboard-visibility-v13-css"' in html
    assert 'id="sentrix-dashboard-visibility-v13-js"' in html
    assert "__sentrixDashboardVisibilityV13" in html
    assert "sxCaptchaV13" in html
    assert "CAPTCHA V96 RÉEL" in html
    assert "verifyPublish" in html
    for retired in ("ensureCurrent", "ensureNav", "setInterval", "data-sx13-tab", "openGrowth", "a.render("):
        assert retired not in html, retired


def test_visibility_v13_requires_the_v12_api_marker_instead_of_creating_it():
    fake = _fake(with_api_marker=False)
    assert v13.install(fake) is False
    assert "__sentrixGrowthV12Api" not in fake.INDEX_HTML


def test_visibility_v13_is_idempotent():
    fake = _fake()
    assert v13.install(fake) is True
    once = fake.INDEX_HTML
    assert v13.install(fake) is True
    assert fake.INDEX_HTML == once
