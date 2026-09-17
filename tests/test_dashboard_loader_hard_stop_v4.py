from web.dashboard_loader_hard_stop_v4 import MARKER, patch_html


def _sample_html() -> str:
    return """<!doctype html>
<html><head></head><body>
<div id=\"sxLoadingExperience\">loading</div>
<div id=\"sxDirectLoader\">loading</div>
<div id=\"content\" aria-busy=\"true\"></div>
</body></html>"""


def test_blocking_loaders_are_forced_hidden_and_removed():
    html = patch_html(_sample_html())
    assert MARKER in html
    assert "#sxLoadingExperience" in html
    assert "#sxDirectLoader" in html
    assert "display:none!important" in html
    assert '["sxLoadingExperience", "sxDirectLoader"]' in html
    assert "node.remove()" in html
    assert 'removeAttribute("aria-busy")' in html


def test_hard_stop_is_idempotent():
    once = patch_html(_sample_html())
    twice = patch_html(once)
    assert once == twice
    assert twice.count('id="sentrix-loader-hard-stop-v4"') == 1


def test_hard_stop_survives_document_without_body_terminator():
    html = patch_html("<html><div id='sxLoadingExperience'></div>")
    assert MARKER in html
    assert "sentrix-loader-hard-stop-v4-js" in html
