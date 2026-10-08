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
        'role="checkbox"',
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
