from types import SimpleNamespace

from web import dashboard_native_bundle_v14 as v14


def _html():
    return '''<!doctype html><html><head></head><body>
<script id="sentrix-dashboard-unified-v2">
(()=>{
const state={};
function renderVerification(){return "<b>CAPTCHA</b><span>Demande le code visuel avant d’attribuer le rôle.</span>"+card('Règlement & vérification','Écrivez le texte exact présenté aux membres.','x')}
})();
</script>
<script id="sentrix-unified-adapter-v9-js">(()=>{window.__v9NativeTest=true})();</script>
<script id="sentrix-growth-v12-js">(()=>{window.__v12NativeTest=true;const x="Réactions automatiques";const y="Statistiques"})();</script>
<script id="sentrix-dashboard-visibility-v13-js">(()=>{window.__v13NativeTest=true;const z="CAPTCHA V96 RÉEL"})();</script>
</body></html>'''


def test_v14_embeds_controllers_in_canonical_script():
    dashboard = SimpleNamespace(INDEX_HTML=_html())
    assert v14.install(dashboard) is True
    html = dashboard.INDEX_HTML
    base_start = html.index('id="sentrix-dashboard-unified-v2"')
    base_end = html.index('</script>', base_start)
    base = html[base_start:base_end]
    assert v14.MARKER in base
    assert "__v9NativeTest" in base
    assert "__v12NativeTest" in base
    assert "__v13NativeTest" in base
    assert "CAPTCHA V96 RÉEL" in html


def test_v14_is_idempotent():
    dashboard = SimpleNamespace(INDEX_HTML=_html())
    assert v14.install(dashboard) is True
    once = dashboard.INDEX_HTML
    assert v14.install(dashboard) is True
    assert dashboard.INDEX_HTML == once
