from types import SimpleNamespace

from web import dashboard_button_system_v24 as v24


def _dashboard():
    return SimpleNamespace(
        INDEX_HTML='<!doctype html><html><head></head><body><button class="btn primary">Créer</button></body></html>'
    )


def test_v24_installs_once_without_replacing_real_dashboard_content():
    dashboard = _dashboard()
    assert v24.install(dashboard) is True
    html = dashboard.INDEX_HTML
    assert html.count('id="sentrix-dashboard-button-system-v24"') == 1
    assert html.count('id="sentrix-dashboard-button-system-v24-js"') == 1
    assert "__sentrixDashboardButtonSystemV24" in html
    assert '<button class="btn primary">Créer</button>' in html

    first = dashboard.INDEX_HTML
    assert v24.install(dashboard) is True
    assert dashboard.INDEX_HTML == first


def test_v24_has_complete_semantic_color_and_interaction_states():
    style = v24.STYLE

    # SentriX semantic palette.
    assert "--sx24-blue:#2563eb" in style
    assert "--sx24-blue-hover:#3b82f6" in style
    assert "--sx24-success:#22c55e" in style
    assert "--sx24-warning:#f59e0b" in style
    assert "--sx24-danger:#ef4444" in style
    assert "--sx24-secondary:#18212b" in style

    for intent in ("primary", "success", "warning", "danger", "ghost", "icon", "server"):
        assert f'[data-sx24-intent="{intent}"]' in style

    assert ":focus-visible" in style
    assert ":disabled" in style
    assert '[aria-disabled="true"]' in style
    assert '[aria-busy="true"]' in style
    assert ":hover" in style
    assert ":active" in style
    assert "min-height:44px" in style
    assert "@media(prefers-reduced-motion:reduce)" in style
    assert "@media(forced-colors:active)" in style


def test_v24_classifies_dynamic_buttons_by_real_action_intent_without_polling():
    script = v24.SCRIPT

    assert "setInterval(" not in script
    assert "MutationObserver" in script
    assert "data-sx24-intent" not in script  # assignment uses dataset, not fragile HTML rewriting
    assert "sx24Intent" in script
    assert 'node.classList.contains("danger")' in script
    assert 'node.classList.contains("primary")' in script
    assert 'node.dataset.sx24Intent = "danger"' in script
    assert 'node.dataset.sx24Intent = "warning"' in script
    assert 'node.dataset.sx24Intent = "success"' in script
    assert 'node.dataset.sx24Intent = "primary"' in script
    assert 'node.dataset.sx24Intent = "secondary"' in script
    assert 'node.dataset.sx24Intent = "ghost"' in script
    assert 'node.dataset.sx24Intent = "icon"' in script
    assert 'node.dataset.sx24Intent = "server"' in script
    assert "supprimer" in script and "ban" in script and "kick" in script
    assert "timeout" in script and "désactiver" in script
    assert "activer" in script and "confirmer" in script
    assert "créer" in script and "enregistrer" in script and "réparer" in script


def test_v24_is_last_visual_authority_after_v23():
    source = open("sentrix_dashboard_finalizer_v7.py", encoding="utf-8").read()
    assert "from web import dashboard_button_system_v24" in source
    assert "dashboard_button_system_v24.install(dashboard)" in source
    assert source.index("dashboard_visual_finish_v23.install(dashboard)") < source.index(
        "dashboard_button_system_v24.install(dashboard)"
    )
    assert 'id="sentrix-dashboard-button-system-v24"' in source
    assert "buttons_v24" in source
