from web.dashboard_pages_v3 import apply_dashboard_pages


BASE = """<html><head><style>.old{color:red}
  </style></head><body>
      <aside class="side"><div class="brand"></div><nav id="navigation"></nav></aside>
      <main class="workspace"><div class="workspace-head"><div><h1 id="pageTitle"></h1><p id="pageSubtitle"></p></div></div></main>
<script>
    const tabs={general:{fields:[]},welcome:{fields:[]},security:{fields:[]},tickets:{fields:[]},logs:{fields:[]}};
    const state={tab:"general"}; const studioMeta={};
    Promise.all([loadPublic(),loadSession()]).catch(e=>toast(e.message,true));
</script></body></html>"""


def test_dashboard_pages_v3_is_now_a_small_compatibility_layer():
    """V3 ne doit plus reconstruire toute l'UI : V60 possède le document final.

    Cette fonction reste utilisée pour les anciennes extensions qui ont besoin du créateur
    d'embeds. Son contrat actuel est donc d'enrichir sans remplacer la page reçue et sans
    réintroduire les générations Oxyde/V5/Clarity/Compact.
    """
    dashboard = apply_dashboard_pages(BASE)
    assert "<html>" in dashboard and "</html>" in dashboard
    assert 'id="navigation"' in dashboard
    assert ".old{color:red}" in dashboard
    assert "sentrix-v56-embeds" in dashboard
    assert "renderEmbeds" in dashboard
    assert "Oxyde" not in dashboard
    assert "Mode avancé guidé" not in dashboard


def test_dashboard_pages_v3_keeps_the_original_boot_program():
    dashboard = apply_dashboard_pages(BASE)
    assert "Promise.all([loadPublic(),loadSession()])" in dashboard
    assert "const tabs=" in dashboard
    # La couche de compatibilité n'invente plus de navigation/hash ou de domaines :
    # le frontend V60 complet les possède directement dans dashboard_rework_v60.py.
    assert "sentrix-v56-embeds" in dashboard


def test_dashboard_pages_v3_is_idempotent():
    once = apply_dashboard_pages(BASE)
    twice = apply_dashboard_pages(once)
    assert twice == once
