"""The actual /app response must use exactly one minimal-motion controller."""
from pathlib import Path
from web import dashboard_quiet_motion_v29 as calm

ROOT = Path(__file__).resolve().parents[1]


def test_quiet_skin_installed_once_before_native_script():
    sample = (
        '<!doctype html><html><head><title>SentriX</title></head>'
        '<body><script id="sentrix-dashboard-unified-v2">(() => {})();</script></body></html>'
    )
    html = calm.enhance(sample)
    assert html.count('id="sentrix-dashboard-quiet-motion-v29"') == 1
    assert html.count('id="sentrix-dashboard-quiet-motion-v29-boot"') == 1
    assert html.index('window.__sentrixQuietMotionV29=true;') < html.index('id="sentrix-dashboard-unified-v2"')
    assert calm.enhance(html) == html
    assert calm.enhance("<html>No head</html>") == "<html>No head</html>"


def test_quiet_motion_is_reduced_mobile_and_performance_safe():
    css = calm.STYLE
    assert "sx29-page-in" in css
    assert "170ms" in css
    assert "body.dashboard-locked::before" in css
    assert "animation:none!important" in css
    assert "@media(max-width:768px)" in css
    assert "prefers-reduced-motion:reduce" in css
    assert "setInterval" not in calm.BOOT
    assert "MutationObserver" not in calm.BOOT
    assert "AudioContext" not in calm.BOOT


def test_request_time_bridge_and_legacy_motion_guards():
    wrapper = (ROOT / "web/dashboard_native_bundle_v14.py").read_text(encoding="utf-8")
    assert "enhance_quiet_motion(html)" in wrapper
    assert "inject_late_motion_into_native_v2(source)" in wrapper
    for path in (
        "web/dashboard_motion_system_v25.py",
        "web/dashboard_visible_motion_v26.py",
        "web/dashboard_motion_audio_v27.py",
    ):
        source = (ROOT / path).read_text(encoding="utf-8")
        assert "if (window.__sentrixQuietMotionV29)" in source
