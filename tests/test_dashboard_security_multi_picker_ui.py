"""Garantit que le dashboard réel utilise les nouveaux multi-sélecteurs AutoMod."""
from pathlib import Path

from web import dashboard_unified_v2 as dashboard


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "web/dashboard_ui/js/30_modules.js").read_text(encoding="utf-8")
STYLES = (ROOT / "web/dashboard_ui/app.css").read_text(encoding="utf-8")


def test_security_pickers_are_in_the_actual_dashboard_bundle():
    html = dashboard.INDEX_HTML
    assert "function bindSecurityMultiPickers(" in html
    assert "function securityMultiPickerMarkup(" in html
    assert "securityPolicyBypassRoles" in html
    assert "securityPolicyStrictChannels" in html
    assert 'data-security-multi=' in html
    assert 'data-security-chips' in html
    assert 'data-security-search' in html
    assert '<select id="securityPolicyBypassRoles" multiple size="6">' not in html
    assert '<select id="securityPolicyStrictChannels" multiple size="7">' not in html


def test_policy_scope_roles_and_strict_channels_are_unchanged():
    assert "policy.supports_policy ? " in SCRIPT
    assert "policyKey" in SCRIPT
    assert "strict_channel_ids: strictChannelIds" in SCRIPT
    assert "role_ids: roleIds" in SCRIPT
    assert "selectedValues($('securityPolicyBypassRoles'))" in SCRIPT
    assert "selectedValues($('securityPolicyStrictChannels'))" in SCRIPT
    assert "const policyDraftKey = `${state.guildId}:${policyKey}`;" in SCRIPT
    assert "if (clearStrict) " not in SCRIPT or "strictChannelIds" in SCRIPT


def test_accessible_chips_and_responsive_search_are_present():
    for phrase in (
        "setAttribute('role', 'checkbox')",
        'aria-checked',
        "setAttribute('aria-expanded'",
        "event.key === 'Escape'",
        'security-multi-chip-remove',
        "select.dispatchEvent(new Event('change'",
        "option.textContent",
        "create('span', 'security-multi-chip-label'",
    ):
        assert phrase in SCRIPT
    assert 'max-width:650px' in STYLES
    assert '.security-multi-popover' in STYLES
    assert '.security-multi-option-checked' in STYLES


def test_native_multiple_select_fallback_cannot_collapse_to_36_pixels():
    # Les anciennes listes visibles possèdent size=6/7. La règle générique
    # .field select (36px) ne doit plus les limiter à seulement deux lignes.
    assert ".field select[multiple]:not([hidden])" in STYLES
    native_rule = STYLES.split(".field select[multiple]:not([hidden]){", 1)[1].split("}", 1)[0]
    assert "height:auto;" in native_rule
    assert "min-height:150px;" in native_rule
    assert "overflow-y:auto;" in native_rule
    # Le select de stockage du picker premium reste caché.
    assert '<select id="${esc(id)}" multiple hidden' in SCRIPT


def test_clear_buttons_stage_only_and_require_explicit_save():
    # Le dashboard ne doit pas écraser une politique de sécurité après un
    # clic accidentel sur « Aucun salon strict » ou « Retirer les rôles ».
    assert "const saveSecurityPolicy = async () =>" in SCRIPT
    assert "clearSecurityPickerSelection($('securityPolicyBypassRoles'))" in SCRIPT
    assert "clearSecurityPickerSelection($('securityPolicyStrictChannels'))" in SCRIPT
    assert "saveSecurityPolicy({ clearRoles: true })" not in SCRIPT
    assert "saveSecurityPolicy({ clearStrict: true })" not in SCRIPT
    assert "if (changed) select.dispatchEvent(new Event('change', { bubbles: true }))" in SCRIPT
    assert "select.addEventListener('change', () =>" in SCRIPT
    assert "state.securityPolicyDrafts[policyDraftKey] = {" in SCRIPT
    assert "role_ids: roleIds" in SCRIPT
    assert "strict_channel_ids: strictChannelIds" in SCRIPT
    assert "if (state.securityPolicyDrafts) delete state.securityPolicyDrafts[policyDraftKey]" in SCRIPT


def test_picker_controls_are_explicitly_labelled_for_screen_readers():
    assert 'aria-label="${esc(label)} : ouvrir les choix"' in SCRIPT
    assert 'data-security-trigger aria-label=' in SCRIPT
    assert "aria-checked" in SCRIPT
