from types import SimpleNamespace

from web import dashboard_motion_audio_v27 as v27
from web import dashboard_native_bundle_v14 as v14


def _html_with_canonical_and_late_v27():
    return (
        '<!doctype html><html><head></head><body><main id="content"></main>'
        '<script id="sentrix-dashboard-unified-v2">(()=>{window.__baseV2=true;})();</script>'
        + v27.SCRIPT
        + '</body></html>'
    )


def test_v28_injects_v27_inside_canonical_unified_v2_program():
    html = _html_with_canonical_and_late_v27()
    patched = v14.inject_late_motion_into_native_v2(html)
    start = patched.index('<script id="sentrix-dashboard-unified-v2">')
    end = patched.index('</script>', start)
    canonical = patched[start:end]

    assert v14.LATE_MOTION_BRIDGE_MARKER in canonical
    assert v27.JS_MARKER in canonical
    assert 'AudioContext' in canonical
    assert 'event.isTrusted' in canonical
    assert 'scale(.925)' in canonical
    assert 'sentrix:v27-page-enter' in canonical


def test_v28_native_injection_is_idempotent():
    first = v14.inject_late_motion_into_native_v2(_html_with_canonical_and_late_v27())
    second = v14.inject_late_motion_into_native_v2(first)
    assert second == first
    start = second.index('<script id="sentrix-dashboard-unified-v2">')
    end = second.index('</script>', start)
    canonical = second[start:end]
    assert canonical.count(v14.LATE_MOTION_BRIDGE_MARKER) == 1
    # The V27 source legitimately references its guard marker twice: once in the
    # early-return check and once in the assignment. Two occurrences therefore
    # mean one injected V27 controller, not two injected controllers.
    assert canonical.count(v27.JS_MARKER) == 2
    assert canonical.count('SentriX V28: execute final V27 motion/audio') == 1


def test_v28_does_not_modify_pages_without_late_v27_source():
    html = '<html><body><script id="sentrix-dashboard-unified-v2">(()=>{})();</script></body></html>'
    assert v14.inject_late_motion_into_native_v2(html) == html


def test_v14_arms_request_time_bridge_even_when_static_bundle_is_already_present():
    async def original(request):
        return None

    dashboard = SimpleNamespace(
        INDEX_HTML=f'<html>{v14.MARKER}</html>',
        handle_index=original,
    )
    assert v14.install(dashboard) is True
    assert getattr(dashboard.handle_index, '_sentrix_native_motion_v28', False) is True
