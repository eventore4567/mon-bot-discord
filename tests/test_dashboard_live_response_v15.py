import asyncio
from types import SimpleNamespace

from aiohttp import web

from web import dashboard_live_response_v15 as v15


def _html():
    return '''<!doctype html><html><head></head><body>
<script id="sentrix-dashboard-unified-v2">
(()=>{
const NAV=[
["Général",[["overview","Vue d’ensemble","OV"],["welcome","Arrivées & départs","AD"],["levels","Niveaux","NV"]]],
["Communauté",[["roles","Rôles","RO"],["economy","Économie","EC"],["notifications","Notifications","NO"]]],
["Outils",[["tickets","Tickets","TI"],["ai","Intelligence artificielle","AI"],["embeds","Embeds & design","EM"]]],
["Administration",[["config","Configuration","CF"],["access","Accès & commandes","AC"],["diagnostic","Diagnostic","DG"]]],
];
const META={diagnostic:["Diagnostic","Permissions, ressources cassées et état des modules."],};
async function renderVerification(){return card('Règlement & vérification','Écrivez le texte exact présenté aux membres.',`<b>CAPTCHA</b><span>Demande le code visuel avant d’attribuer le rôle.</span><button>Enregistrer et publier</button>`)}
async function render(force=false){switch(state.tab){case'diagnostic':await renderDiagnostic();break;default:await renderOverview()}}
})();
</script></body></html>'''


def test_v15_patches_native_nav_render_and_captcha():
    html = v15.patch_html(_html())
    assert v15.MARKER in html
    assert 'name="sentrix-dashboard-build"' in html
    assert "Statistiques" in html
    assert "Réactions automatiques" in html
    assert "Webhooks & intégrations" in html
    assert "case'autoreact':await renderAutoReactV15();break" in html
    assert "CAPTCHA V96 RÉEL" in html
    assert "Enregistrer et publier sur Discord" in html


def test_v15_patch_is_idempotent():
    once = v15.patch_html(_html())
    assert v15.patch_html(once) == once


def test_v15_wraps_the_actual_app_response():
    async def old_handler(_request):
        return web.Response(text=_html(), content_type="text/html")

    dashboard = SimpleNamespace(handle_index=old_handler, INDEX_HTML=_html())
    assert v15.install(dashboard) is True

    request = SimpleNamespace(path="/app")
    response = asyncio.run(dashboard.handle_index(request))
    assert response.headers["X-SentriX-Dashboard-Build"] == v15.BUILD
    assert response.headers["X-SentriX-Dashboard-Nav"] == "1"
    assert response.headers["X-SentriX-Dashboard-Captcha"] == "1"
    assert v15.MARKER in response.text
    assert "Réactions automatiques" in response.text
    assert "CAPTCHA V96 RÉEL" in response.text
