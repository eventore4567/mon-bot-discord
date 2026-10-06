from __future__ import annotations

import inspect

from cogs import staff_suite
from database import db as db_module


def test_modview_is_server_wide_and_has_manual_lookup_fallback():
    source = inspect.getsource(staff_suite)
    assert 'name="modview"' in source
    assert "class ModViewMemberSelect" in source
    assert "class ModViewLookupModal" in source
    assert "query_members" in source
    assert "fetch_member" in source
    assert "pas seulement sur les membres" in source


def test_modview_member_panel_exposes_real_moderation_actions():
    source = inspect.getsource(staff_suite.MemberPanelView)
    for label in ('label="Avertir"', 'label="Timeout"', 'label="Expulser"', 'label="Bannir"'):
        assert label in source
    assert 'label="Sanctions"' in source


def test_sanction_history_is_paginated_and_reason_is_editable():
    history = inspect.getsource(staff_suite.SanctionHistoryView)
    detail = inspect.getsource(staff_suite.SanctionDetailView)
    modal = inspect.getsource(staff_suite.SanctionReasonModal)
    assert 'label="Précédent"' in history
    assert 'label="Suivant"' in history
    assert 'label="Modifier la raison"' in detail
    assert "update_sanction_reason" in modal


def test_sanction_reason_edits_are_audited_in_database():
    source = inspect.getsource(db_module)
    assert "CREATE TABLE IF NOT EXISTS sanction_reason_edits_v1" in source
    assert "old_reason TEXT" in source
    assert "new_reason TEXT NOT NULL" in source
    assert hasattr(db_module.Database, "update_sanction_reason")
    assert hasattr(db_module.Database, "get_sanction_reason_edits")


def test_modview_sanction_history_has_filters_and_pagination():
    source = inspect.getsource(staff_suite)
    assert "class SanctionFilterSelect" in source
    for label in (
        "Toutes les sanctions",
        "Bannissements",
        "Timeouts",
        "Avertissements",
        "Expulsions",
        "Levées de sanction",
    ):
        assert label in source
    assert "action_filter" in inspect.getsource(staff_suite.StaffSuite.send_sanction_history)
