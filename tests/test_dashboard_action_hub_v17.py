from web import dashboard_action_hub_v17 as v17


FINAL_V15_LIKE_HTML = '''<!doctype html><html><head></head><body>
<script id="sentrix-dashboard-unified-v2">
const NAV=[
  ["Outils",[["tickets","Tickets","TI"],["embeds","Embeds & design","EM"],["automations","Automatisations","AU"]]],
  ["Administration",[["config","Configuration","CF"],["diagnostic","Diagnostic","DG"],["staffactivity","Activité staff","AS"],["audit","Historique & audit","HA"],["backups","Sauvegardes","SV"],["maintenance","Maintenance","MT"],["integrations","Webhooks & intégrations","WI"]]]
];
const META={diagnostic:["Diagnostic","Permissions, ressources cassées et état des modules."],staffactivity:["Activité staff","Actions staff des dernières 24 heures."]};
async function render(){switch(state.tab){case'diagnostic':await renderDiagnostic();break;case'staffactivity':await renderStaffV15();break;case'audit':await renderAuditV15();break;case'backups':await renderBackupsV15();break;case'maintenance':await renderMaintenanceV15();break;case'integrations':await renderIntegrationsV15();break;default:await renderOverview()}}
</script>
</body></html>'''


def test_v17_replaces_technical_sidebar_clutter_with_useful_actions():
    patched = v17.patch_html(FINAL_V15_LIKE_HTML)

    assert '["actions","Actions utiles","UT"]' in patched
    assert '["staffactivity","Activité staff","AS"]' not in patched
    assert '["audit","Historique & audit","HA"]' not in patched
    assert '["backups","Sauvegardes","SV"]' not in patched
    assert '["maintenance","Maintenance","MT"]' not in patched
    assert '["integrations","Webhooks & intégrations","WI"]' not in patched
    assert '["automations","Automatisations","AU"]' not in patched

    # Old render cases remain valid for old bookmarks even though they are not in the menu.
    assert "case'staffactivity':await renderStaffV15();break;" in patched
    assert "case'maintenance':await renderMaintenanceV15();break;" in patched
    assert "case'actions':await renderActionsV17();break;" in patched


def test_v17_only_exposes_controls_backed_by_existing_routes_or_pages():
    patched = v17.patch_html(FINAL_V15_LIKE_HTML)

    assert '/ops/repair' in patched
    assert '/ops/export' in patched
    assert '/ops/import' in patched
    assert '/ops/maintenance' in patched
    assert '/ops/policies' in patched
    assert '/ops/history/' in patched

    # Shortcuts are generated at runtime by v17Shortcut(), so assert the actual renderer
    # calls rather than looking for already-expanded HTML attributes in the source script.
    for tab in ('autoreact', 'embeds', 'tickets', 'economy', 'notifications', 'welcome'):
        assert f"v17Shortcut('{tab}'" in patched
    assert 'data-v17-go=' in patched
    assert "go(b.dataset.v17Go)" in patched

    assert "Giveaway" not in patched
    assert "Quiz" not in patched


def test_v17_injects_native_assets_and_is_idempotent():
    once = v17.patch_html(FINAL_V15_LIKE_HTML)
    twice = v17.patch_html(once)

    assert once == twice
    assert once.count('sentrix-dashboard-action-hub-v17') == 1
    assert once.count('__sentrixActionHubV17') >= 1
    assert 'function renderActionsV17()' in once
    assert 'name="sentrix-dashboard-action-build"' in once
