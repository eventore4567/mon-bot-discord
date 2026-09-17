from sentrix_dashboard_finalizer_v7 import _stabilize_background_loading


def _sample_html() -> str:
    return """<!doctype html><html><body>
<script>
async function boot(){renderNav();loadPublic();setInterval(loadPublic,30000);await loadSession()}
</script>
<div id=\"sentrix-progress\"></div>
</body></html>"""


def test_public_polling_no_longer_runs_every_30_seconds():
    html = _stabilize_background_loading(_sample_html())
    assert "setInterval(loadPublic,30000)" not in html
    assert "visibilitychange" in html
    assert "if(!document.hidden)loadPublic()" in html


def test_background_requests_do_not_show_foreground_progress():
    html = _stabilize_background_loading(_sample_html())
    assert 'id="sentrix-background-loading-guard-v3"' in html
    assert 'path === "/api/public"' in html
    assert 'path === "/health"' in html
    assert 'path.includes("/live/")' in html
    assert "html.sx-background-fetch #sentrix-progress" in html
    assert "setTimeout(() =>" in html
    assert "260" in html


def test_background_guard_is_idempotent():
    once = _stabilize_background_loading(_sample_html())
    twice = _stabilize_background_loading(once)
    assert once == twice
    assert twice.count('id="sentrix-background-loading-guard-v3"') == 1
