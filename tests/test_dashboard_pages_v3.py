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


def test_v3_installs_real_page_navigation():
    dashboard = apply_dashboard_pages(BASE)

    assert "function installPageShell" in dashboard
    assert "function renderOverviewPage" in dashboard
    assert "function renderCaptchaPage" in dashboard
    assert "function renderMessagePage" in dashboard
    assert "function renderWhitelistPage" in dashboard
    assert "function renderTicketsIndex" in dashboard
    assert 'location.hash=b.dataset.tab' in dashboard


def test_v3_uses_sentrix_blue_copy_without_old_hub():
    dashboard = apply_dashboard_pages(BASE)

    assert "#398bff" in dashboard
    assert "Messages de bienvenue" in dashboard
    assert "Protection AntiRaid" in dashboard
    assert "Configuration des tickets" in dashboard
    assert "Logs du serveur" in dashboard
    assert "Mode avancé guidé" not in dashboard
    assert "Oxyde" not in dashboard
