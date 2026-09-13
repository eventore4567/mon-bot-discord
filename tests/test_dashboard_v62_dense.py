from __future__ import annotations


def _document():
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    return dashboard, str(dashboard.INDEX_HTML)


def test_unified_document_contains_real_v62_inline_editors():
    dashboard, document = _document()
    assert getattr(dashboard, "_sentrix_dashboard_version", None) == "unified-v2"
    for marker in (
        'id="sentrix-dashboard-unified-v2"',
        'id="sentrix-unified-runtime-v2"',
        "Vérification",
        "Enregistrer et publier",
        "verifyPublish",
        "ticketSave",
        "ticketPublish",
        "/v62",
        "--blue:#4da3ff",
        "Aperçu Discord",
    ):
        assert marker in document, marker

    for legacy in (
        'id="sentrix-v62-compat"',
        'id="sentrix-v62-dense"',
        'id="sentrix-v63-polish"',
        'id="sentrix-v64-final"',
    ):
        assert legacy not in document


def test_unified_sidebar_does_not_restore_empty_secondary_navigation():
    _dashboard, document = _document()
    for removed in ('["recurring"', '["community"', '["features"', '["infinity"'):
        assert removed not in document
    for present in ('["verification"', '["economy"', '["tickets"', '["dm"'):
        assert present in document
    assert "Messages récurrents" not in document
    assert "Fonctions avancées" not in document


def test_v62_backend_routes_are_bound_in_the_final_build_chain():
    dashboard, _document_text = _document()
    function = getattr(dashboard.build_app, "__func__", dashboard.build_app)
    seen = set()
    while function is not None and id(function) not in seen:
        if getattr(function, "_sentrix_v62_routes", False):
            return
        seen.add(id(function))
        function = getattr(function, "_sentrix_original", None)
    raise AssertionError("les routes V62 ne sont pas présentes dans la chaîne build_app")
