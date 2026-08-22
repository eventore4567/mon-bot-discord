from web.dashboard_theme_v2 import apply_dashboard_theme


BASE = """<html><head><style>.old{color:red}
  </style></head><body>
      <nav class="nav" id="navigation">
        <button data-tab="general" class="active">Général</button>
        <button data-tab="security">Sécurité</button>
        <button data-tab="sanctions">Sanctions</button>
        <button data-tab="logs">Logs</button>
        <button data-tab="welcome">Accueil</button>
        <button data-tab="levels">Niveaux</button>
        <button data-tab="tickets">Tickets</button>
        <button data-tab="ai">Intelligence artificielle</button>
        <button data-tab="notifications">Notifications</button>
        <button data-tab="roles">Rôles et salons</button>
      </nav>
      <div class="workspace-head">
        <div><h1 id="pageTitle">Dashboard</h1><p id="pageSubtitle">Choisissez un serveur que vous gérez.</p></div>
        <select id="serverSelect" class="select server-select"><option value="">Chargement des serveurs…</option></select>
      </div>
<script>const marker=true;
    Promise.all([loadPublic(),loadSession()]).catch(e=>toast(e.message,true));</script></body></html>"""


def test_theme_adds_blue_design_system_and_dedicated_views():
    themed = apply_dashboard_theme(BASE)

    assert "--brand:#2f7dff" in themed
    assert "Vue d'ensemble" in themed
    assert 'id="pageEyebrow"' in themed
    assert "function renderModuleGrid" in themed
    assert "function renderLogStudio" in themed
    assert "function renderWelcomeStudio" in themed
    assert "function renderTicketStudio" in themed


def test_theme_keeps_original_brand_copy():
    themed = apply_dashboard_theme(BASE)

    assert "SentriX" in themed
    assert "Oxyde" not in themed
