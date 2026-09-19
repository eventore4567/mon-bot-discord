from __future__ import annotations


def _final_document() -> str:
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    return str(dashboard.INDEX_HTML)


def test_unified_matches_requested_sentrix_shell_with_blue_details():
    document = _final_document()

    assert "<title>SentriX — Dashboard</title>" in document
    assert "SentriX<small>Dashboard</small>" in document

    # Palette propre à SentriX : charbon + bleu, sans reprendre le branding d'un tiers.
    assert "--bg:#0b0d10" in document
    assert "--panel:#15191f" in document
    assert "--blue:#4da3ff" in document
    assert "--blue2:#77bcff" in document
    assert "--accent:#d66f55" not in document

    # Un seul shell : rail serveurs + sidebar + zone centrale.
    assert 'class="server-rail"' in document
    assert 'class="sidebar"' in document
    assert 'class="workspace"' in document
    assert "const NAV = [" in document
    assert 'id="sentrix-dashboard-unified-v2"' in document


def test_unified_mobile_and_tablet_layout_is_explicitly_hardened():
    document = _final_document()

    for marker in (
        "@media (max-width:1100px)",
        "@media (max-width:900px)",
        ".sidebar.open{transform:none}",
        ".grid{grid-template-columns:1fr}",
        ".module-grid{grid-template-columns:1fr}",
        "closeSidebar();",
        "prefers-reduced-motion:reduce",
    ):
        assert marker in document, marker


def test_unified_keeps_requested_pages_inside_the_same_app():
    document = _final_document()

    for label in (
        "Vue d’ensemble",
        "Accueil & Départs",
        "Niveaux",
        "Économie",
        "Rôles",
        "Sécurité",
        "Logs",
        "Tickets",
        "Notifications",
        "Automatisation",
        "Paramètres",
        "Commandes & accès",
        "Intelligence artificielle",
        "Message privé",
        "Diagnostic",
    ):
        assert label in document, label

    for legacy in (
        "Messages récurrents",
        'id="sentrix-v64-final"',
        'id="sxFeaturesFrame"',
    ):
        assert legacy not in document
