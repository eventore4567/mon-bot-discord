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


def test_dashboard_pages_produce_a_navigable_page():
    """Le dashboard est passe en V4 « Oxyde » : on teste ce qu'il garantit aujourd'hui.

    Les anciennes assertions epinglaient des noms de fonctions et une couleur de la
    generation V3 (installPageShell, #398bff, absence d'« Oxyde »). Elles decrivaient
    une page qui n'existe plus. Ce qui doit rester vrai, c'est que la fonction enrichit
    la page de base sans la casser et qu'elle installe une vraie navigation.
    """
    dashboard = apply_dashboard_pages(BASE)

    # La page de base doit avoir ete enrichie, pas remplacee.
    assert len(dashboard) > len(BASE) * 10
    assert "<html>" in dashboard and "</html>" in dashboard
    assert 'id="navigation"' in dashboard

    # Navigation par ancre : chaque onglet est adressable.
    assert "location.hash" in dashboard
    assert "data-tab" in dashboard


def test_dashboard_covers_every_configurable_domain():
    dashboard = apply_dashboard_pages(BASE).casefold()
    for domain in ("bienvenue", "sécurité", "ticket", "logs", "antiraid"):
        assert domain.casefold() in dashboard, domain


def test_dashboard_drops_the_old_guided_advanced_mode():
    dashboard = apply_dashboard_pages(BASE)
    assert "Mode avancé guidé" not in dashboard
