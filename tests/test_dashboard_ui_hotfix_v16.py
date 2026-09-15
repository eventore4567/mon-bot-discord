from web import dashboard_ui_hotfix_v16 as v16


def test_v16_renames_verification_and_injects_compact_switch_css():
    html = '''<!doctype html><html><head></head><body>
<script id="sentrix-dashboard-unified-v2">
const NAV=[["Sécurité & modération",[["logs","Logs","LG"],["verification","Vérification","VE"]]]];
const META={verification:["Vérification","Écrivez votre règlement et publiez le panneau de vérification réel."]};
</script>
<div class="fields"><label class="switch-row field full"><span class="switch-copy"><b>Ignorer les bots</b></span><input class="switch" type="checkbox"></label></div>
</body></html>'''

    patched = v16.patch_html(html)

    assert '["verification","Vérification Discord","VE"]' in patched
    assert 'verification:["Vérification Discord"' in patched
    assert 'id="sentrix-dashboard-ui-hotfix-v16"' in patched
    assert '.field input.switch' in patched
    assert 'width:38px !important' in patched
    assert 'flex:0 0 38px !important' in patched


def test_v16_restores_verification_entry_if_late_layer_dropped_it():
    html = '''<!doctype html><html><head></head><body>
<script id="sentrix-dashboard-unified-v2">
const NAV=[["Sécurité & modération",[["security","Sécurité","SE"],["logs","Logs","LG"]]]];
</script>
</body></html>'''

    patched = v16.patch_html(html)

    assert '["logs","Logs","LG"],["verification","Vérification Discord","VE"]' in patched


def test_v16_patch_is_idempotent():
    html = '<!doctype html><html><head></head><body>["verification","Vérification","VE"]</body></html>'
    once = v16.patch_html(html)
    twice = v16.patch_html(once)

    assert once == twice
    assert twice.count('sentrix-dashboard-ui-hotfix-v16') == 1
