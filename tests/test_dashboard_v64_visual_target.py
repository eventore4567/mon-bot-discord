from __future__ import annotations


def _final_document() -> str:
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    return str(dashboard.INDEX_HTML)


def test_v64_matches_requested_sentrix_coral_shell():
    document = _final_document()

    # Identité SentriX : le dashboard s'inspire du shell fourni sans reprendre son branding.
    assert "<title>SentriX — Dashboard</title>" in document
    assert "SENTR<em>IX</em>" in document

    # Palette demandée : charbon + corail/orange. V64 remappe aussi les anciens alias bleus
    # afin qu'une couche V62/V63 ne puisse pas reprendre le dessus visuellement.
    assert "--accent:#d66f55" in document
    assert "--accent2:#ef8568" in document
    assert "--sx-blue:var(--accent,#d66f55)" in document
    assert ".btn.blue{background:var(--accent,#d66f55)!important" in document
    assert ".navigation .sx-nav-search:focus{border-color:var(--accent,#d66f55)" in document

    # Le shell final doit rester monolithique : rail serveurs + sidebar + zone centrale.
    assert 'class="server-rail"' in document
    assert 'class="sidebar"' in document
    assert 'class="workspace"' in document
    assert "const FINAL_GROUPS" in document


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
