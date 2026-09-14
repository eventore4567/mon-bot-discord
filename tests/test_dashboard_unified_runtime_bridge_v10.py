from types import SimpleNamespace

from web import dashboard_unified_runtime_bridge_v10 as bridge


def test_bridge_exposes_unified_v2_lexical_runtime():
    html = '''<html><body><script id="sentrix-dashboard-unified-v2">\n(() => {\n"use strict";\nconst state={user:null,sanctionsPage:0};\nfunction go(){}\nfunction refreshAll(){}\nfunction v62Action(){}\nfunction toast(){}\n})();\n</script></body></html>'''
    dashboard = SimpleNamespace(INDEX_HTML=html)
    assert bridge.install(dashboard) is True
    out = dashboard.INDEX_HTML
    assert "__sentrixUnifiedRuntimeV10" in out
    assert "window.state=state" in out
    assert "window.go=go" in out
    assert "window.refreshAll=refreshAll" in out
    assert "window.v62Action=v62Action" in out
    assert "window.toast=toast" in out


def test_bridge_is_idempotent():
    html = '''<script id="sentrix-dashboard-unified-v2">const state={sanctionsPage:0};</script>'''
    dashboard = SimpleNamespace(INDEX_HTML=html)
    assert bridge.install(dashboard) is True
    once = dashboard.INDEX_HTML
    assert bridge.install(dashboard) is True
    assert dashboard.INDEX_HTML == once


def test_finalizer_requires_runtime_bridge_before_v9():
    source = open("sentrix_dashboard_finalizer_v7.py", encoding="utf-8").read()
    assert "dashboard_unified_runtime_bridge_v10.install(dashboard)" in source
    assert "dashboard_unified_adapter_v9.install(dashboard)" in source
    assert source.index("dashboard_unified_runtime_bridge_v10.install(dashboard)") < source.index("dashboard_unified_adapter_v9.install(dashboard)")
    assert "__sentrixUnifiedRuntimeV10" in source
