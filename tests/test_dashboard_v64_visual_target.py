from __future__ import annotations


def _final_document() -> str:
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    return str(dashboard.INDEX_HTML)


def test_v64_matches_requested_sentrix_shell_with_blue_details():
    document = _final_document()

    # Identité SentriX : le dashboard s'inspire du shell fourni sans reprendre son branding.
    assert "<title>SentriX — Dashboard</title>" in document
    assert "SENTR<em>IX</em>" in document

    # Palette finale : charbon/corail pour le shell et vraies touches bleues SentriX.
    assert "--accent:#d66f55" in document
    assert "--accent2:#ef8568" in document
    assert "--sx-blue:#4da3ff" in document
    assert "--sx-blue2:#78bdff" in document
    assert "--sx-blue:var(--accent,#d66f55)" not in document
    assert ".btn.blue{background:var(--sx-blue,#4da3ff)!important" in document
    assert ".navigation .sx-nav-search:focus{border-color:var(--sx-blue,#4da3ff)" in document

    # Le shell final doit rester monolithique : rail serveurs + sidebar + zone centrale.
    assert 'class="server-rail"' in document
    assert 'class="sidebar"' in document
    assert 'class="workspace"' in document
    assert "const FINAL_GROUPS" in document


def test_v64_mobile_and_tablet_layout_is_explicitly_hardened():
    document = _final_document()

    for marker in (
        "@media(max-width:1180px)",
        "@media(max-width:820px)",
        "@media(max-width:540px)",
        "width:min(86vw,300px)!important",
        "overflow-x:hidden!important",
        ".grid2,.embed-builder,.fields-grid,.action-grid,.sx-v62-grid,.sx-v63-modules,.sx-v63-palette,.sx-v63-economy{grid-template-columns:1fr!important}",
        ".metrics{grid-template-columns:1fr!important}",
        "if(innerWidth<821)$('sidebar')?.classList.remove('open')",
    ):
        assert marker in document, marker


def test_v64_keeps_requested_pages_inside_the_same_app():
    document = _final_document()
    final = document[document.index("const FINAL_GROUPS"):document.index("let lastSearch", document.index("const FINAL_GROUPS"))]

    for label in (
        "Vue d’ensemble",
        "Arrivées et départs",
        "Rôles automatiques",
        "Rôles sécurisés",
        "Rôles-réactions",
        "Vérification & règlement",
        "Modération",
        "Auto-Modération",
        "Signalements",
        "Logs",
        "Économie",
        "Notifications sociales",
        "Tickets",
        "Intelligence artificielle",
        "Embeds",
        "Mini-jeux",
        "Design",
        "Configuration serveur",
        "Accès & commandes",
        "Messages privés",
        "Statut SentriX",
    ):
        assert label in final, label

    for legacy in ("Fonctions avancées", "Messages récurrents", "/feature-suite", "/setup-center"):
        assert legacy not in final
