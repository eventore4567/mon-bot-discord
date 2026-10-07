from __future__ import annotations

import inspect

from cogs import slash_command_budget
from cogs import staff_suite
from utils import access_matrix


def test_staff_suite_exposes_the_premium_entry_points():
    source = inspect.getsource(staff_suite.StaffSuite)
    for name in (
        'name="member"',
        'name="modview"',
        'name="note"',
        'name="staff-history"',
        'name="incident"',
        'name="watch"',
        'name="staff"',
        'name="handover"',
        'name="urgence"',
        'name="audit"',
        # staff-diagnostic : « diagnostic » appartient a cogs/stats.py. Le
        # doublon faisait echouer add_cog et la suite ENTIERE disparaissait.
        'name="staff-diagnostic"',
        'name="report"',
        'name="absence"',
        'name="staff-reminder"',
    ):
        assert name in source


def test_staff_center_is_panel_first_not_command_syntax_first():
    source = inspect.getsource(staff_suite.StaffCenterView)
    for label in (
        'label="Dossiers"',
        'label="Incidents"',
        'label="Surveillances"',
        'label="Absences"',
        'label="Rapport"',
        'label="Handover"',
        'label="Diagnostic"',
        'label="Rappel"',
        'label="Urgence"',
    ):
        assert label in source


def test_staff_suite_never_creates_channels_or_categories():
    source = inspect.getsource(staff_suite)
    assert "create_text_channel" not in source
    assert "create_category" not in source
    assert "create_voice_channel" not in source


def test_staff_sensitive_commands_are_in_the_access_matrix():
    expected = {
        "member": "moderate_members",
        "modview": "moderate_members",
        "note": "moderate_members",
        "staff-history": "moderate_members",
        "incident": "moderate_members",
        "watch": "moderate_members",
        "staff": "moderate_members",
        "handover": "moderate_members",
        "report": "moderate_members",
        "absence": "moderate_members",
        "staff-reminder": "moderate_members",
        "urgence": "manage_channels",
        "audit": "manage_guild",
    }
    for name, permission in expected.items():
        assert access_matrix.DISCORD_PERMISSION_COMMANDS[name] == permission

    # /diagnostic reste volontairement au niveau configuration/admin existant.
    assert "diagnostic" in access_matrix.CATEGORY_COMMANDS["configuration"]


def test_staff_slash_roots_are_protected_by_the_global_budget():
    assert {"staff", "member", "modview", "case", "diagnostic"} <= slash_command_budget.STAFF_SLASH_PREFERRED
    assert {"staff", "member", "modview", "case", "diagnostic"} <= slash_command_budget._required_names()


def test_watch_panel_is_event_driven_and_has_pause_stop_controls():
    source = inspect.getsource(staff_suite.StaffSuite)
    assert "on_message_delete" in source
    assert "on_message_edit" in source
    assert "on_reaction_add" in source
    assert "on_voice_state_update" in source
    assert "on_presence_update" in source

    controls = inspect.getsource(staff_suite.WatchControlView)
    assert 'label="Pause"' in controls
    assert 'label="Terminer"' in controls


def test_case_command_opens_staff_center_without_breaking_numeric_sanction_lookup():
    from cogs import moderation

    # .callback : un hybrid_command est un objet Command, pas une fonction.
    # inspect.getsource echouait dessus, et la garde ne verifiait donc RIEN.
    source = inspect.getsource(moderation.Moderation.case.callback)
    assert "numero: int | None = None" in source
    assert 'self.bot.get_cog("StaffSuite")' in source
    assert "open_case_center(ctx)" in source
    assert "get_sanction_by_case" in source
