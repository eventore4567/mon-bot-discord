"""Garde UI SentriX Control Center V2.

Vérifie que les pages sensibles et la logique Free n'ont pas été retirées
et que le sélecteur multiple n'est plus contraint à 36px.
"""
from pathlib import Path
from web import dashboard_unified_v2 as ui

DIR = Path(__file__).resolve().parents[1] / "web" / "dashboard_ui"


def test_real_unified_dashboard_uses_richer_overview_not_fake_cards():
    html = ui.INDEX_HTML
    for marker in (
        # Centre de commande : résumé vivant, activité réelle, fil en direct.
        'class="cc-hero full"',
        'class="card cc-activity"',
        'class="card cc-feed"',
        'class="sx-module-section full"',
        'class="module-grid"',
        'data-action="enable"',
        'data-action="disable"',
        "diagnostics(),",
        "const g = state.guild?.guild || {}",
        "gget('/activity')",
        "/live/metrics",
        "function renderNav()",
        "async function selectGuild(value)",
        "const kicker = $('workspaceKicker')",
    ):
        assert marker in html, marker
    assert html.count('id="sentrix-dashboard-unified-v2"') == 1
    assert html.count('id="content"') == 1


def test_security_picker_keeps_backend_policy_contract_and_staff_permissions():
    html = ui.INDEX_HTML
    assert 'id="securityPolicyBypassRoles" multiple>' in html
    assert 'id="securityPolicyStrictChannels" multiple>' in html
    assert 'multiple size="6"' not in html
    assert 'multiple size="7"' not in html
    for marker in (
        "function mountSecurityMultiPicker(id, kind)",
        "mountSecurityMultiPicker('securityPolicyBypassRoles', 'roles')",
        "mountSecurityMultiPicker('securityPolicyStrictChannels', 'channels')",
        "const roleIds = clearRoles ? [] : selectedValues($('securityPolicyBypassRoles'))",
        "const strictChannelIds = clearStrict ? [] : selectedValues($('securityPolicyStrictChannels'))",
        "gpost('/security/filter-policies'",
        "securityPolicySave",
        "securityPolicyClearStrict",
        "securityPolicyClearRoles",
        "securityPolicyClearMembers",
        "selectedSecurityMembers",
        "Salons à surveillance stricte",
    ):
        assert marker in html, marker
    assert "Salons stricts — bypass interdit" not in html


def test_security_picker_corrects_height_and_has_responsive_accessible_ui():
    css = (DIR / "app.css").read_text(encoding="utf-8")
    assert "SentriX Control Center V2" in css
    for marker in (
        ".field select[multiple]:not(.sx-picker-native)",
        ".field select.sx-picker-native[multiple]",
        ".sx-picker-options",
        ".sx-picker-chips",
        ".sx-picker-option[hidden]",
        ".sx-picker-chip:focus-visible",
        ".sx-picker-search",
        "max-height:252px",
        "accent-color:var(--blue)",
        "@media(max-width:700px)",
        "@media(max-width:480px)",
        "@media(prefers-reduced-motion:reduce)",
    ):
        assert marker in css, marker


def test_dashboard_keeps_free_functions_and_core_single_document():
    html = ui.INDEX_HTML
    assert html.count("<style>") == 1
    assert html.count('id="sentrix-dashboard-unified-v2"') == 1
    for marker in (
        "NAV_SERVER", "Rôles", "Tickets", "Sécurité", "Logs", "Accueil & Départs",
        "Économie", "Niveaux", "Musique", "Automatisation", "Notifications",
        "renderSecurity", "renderOverview", "renderWelcome", "renderGames",
        "renderMusic", "renderTickets", "renderLogs", "renderSanctions",
        "/api/me", "/api/guilds", "/security/filter-policies",
        "guardDirty", "saveButton", "discardButton",
    ):
        assert marker in html, marker
