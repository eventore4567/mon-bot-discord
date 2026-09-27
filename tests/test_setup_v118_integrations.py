from pathlib import Path

import sentrix_setup_v116 as v116


SETUP_SOURCE = Path("cogs/setup_v118_integrations.py").read_text(encoding="utf-8")
HONEYPOT_SOURCE = Path("cogs/honeypot_verification_v48.py").read_text(encoding="utf-8")
SECURITY_SETUP_SOURCE = Path("cogs/setup_control_center.py").read_text(encoding="utf-8")
RAILWAY_SOURCE = Path("railway_boot.py").read_text(encoding="utf-8")


def test_v118_compiles():
    compile(SETUP_SOURCE, "cogs/setup_v118_integrations.py", "exec")


def test_v116_exposes_invite_and_advanced_security_sections():
    assert "invitations" in v116.MODULE_BY_KEY
    security = {section.key for section in v116.MODULE_BY_KEY["security"].sections}
    assert {"vanity", "prune", "permissions", "join_gate", "risk"} <= security
    invite_actions = {section.action for section in v116.MODULE_BY_KEY["invitations"].sections}
    assert "internal:invitations" in invite_actions
    verification_actions = {section.action for section in v116.MODULE_BY_KEY["verification"].sections}
    assert "internal:verification" in verification_actions
    assert "rules" in v116.MODULE_BY_KEY
    rule_actions = {section.action for section in v116.MODULE_BY_KEY["rules"].sections}
    assert "internal:rules" in rule_actions


def test_v118_integrates_invite_tracker_inside_setup():
    assert "class InviteTrackerSetupView" in SETUP_SOURCE
    assert "has been invited by" in SETUP_SOURCE
    assert "set_feed_setting" in SETUP_SOURCE
    assert "log_service.set_log_config" in SETUP_SOURCE
    assert 'action == "internal:invitations"' in SETUP_SOURCE


def test_v118_integrates_verification_repair_inside_setup():
    assert "class VerificationSetupView" in SETUP_SOURCE
    assert "create_or_refresh_system" in SETUP_SOURCE
    assert "Activer / mettre à jour" in SETUP_SOURCE
    assert 'action == "internal:verification"' in SETUP_SOURCE
    assert 'action == "internal:rules"' in SETUP_SOURCE
    assert "open_setup_interaction" in SETUP_SOURCE


def test_enabled_honeypot_repairs_missing_panels_on_ready_without_creating_structure():
    assert "async def _repair_enabled_systems" in HONEYPOT_SOURCE
    assert "_repair_enabled_systems(bot)" in HONEYPOT_SOURCE
    assert "sentrix-honeypot-repair" in HONEYPOT_SOURCE
    repair = HONEYPOT_SOURCE[HONEYPOT_SOURCE.index("async def _repair_enabled_systems"):]
    repair = repair[:repair.index("async def install")]
    assert "create_or_refresh_system(" not in repair
    assert "create_text_channel(" not in repair
    assert "create_category(" not in repair
    assert "No channel, category or role is ever created from this startup task" in repair


def test_setup_security_catalogue_contains_new_guards():
    for key in (
        "security_vanity",
        "security_prune",
        "security_permissions",
        "join_gate",
        "risk_engine",
    ):
        assert key in SECURITY_SETUP_SOURCE


def test_railway_loads_invite_tracker_and_setup_v118():
    assert '"cogs.invite_tracker_runtime"' in RAILWAY_SOURCE
    assert '"cogs.setup_v118_integrations"' in RAILWAY_SOURCE
