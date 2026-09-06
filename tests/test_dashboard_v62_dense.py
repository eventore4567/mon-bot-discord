from __future__ import annotations


def _document():
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    return dashboard, str(dashboard.INDEX_HTML)


def test_v63_final_document_contains_dense_inline_editors():
    dashboard, document = _document()
    assert getattr(dashboard, "_sentrix_dashboard_version", None) == "v63-polish"
    for marker in (
        'id="sentrix-v61-unified"',
        'id="sentrix-v62-compat"',
        'id="sentrix-v62-dense"',
        'id="sentrix-v63-polish"',
        "function categoryOptions(current='')",
        "Vérification & règlement",
        "Enregistrer et publier",
        "ticket_panel_save",
        "ticket_type_save",
        "ticket_question_save",
        "ticket_button_save",
        "Règlement & vérification",
        "--sx-blue:#4da3ff",
        "Aperçu Discord",
    ):
        assert marker in document, marker

    # categoryOptions doit être déclaré AVANT le script V62 qui l'utilise.
    assert document.index('id="sentrix-v62-compat"') < document.index('id="sentrix-v62-dense"')


def test_v63_removes_empty_secondary_navigation_from_final_sidebar_program():
    _dashboard, document = _document()
    v62_start = document.index("const V62_GROUPS")
    v62_end = document.index("tabMeta.verification", v62_start)
    groups = document[v62_start:v62_end]
    for removed in ('["recurring"', '["community"', '["features"', '["infinity"'):
        assert removed not in groups
    assert '["verification"' in groups
    assert '["economy"' in groups


def test_v62_backend_routes_are_bound_before_build_app():
    dashboard, _document_text = _document()
    function = getattr(dashboard.build_app, "__func__", dashboard.build_app)
    assert getattr(function, "_sentrix_v62_routes", False)
