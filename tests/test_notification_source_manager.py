from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_notification_manager_has_real_source_selector_and_safe_disabled_actions():
    source = (ROOT / "cogs" / "setup_v2_ui.py").read_text(encoding="utf-8")

    start = source.index("class NotificationManageView")
    end = source.index("async def _permission_decision_for_view", start)
    block = source[start:end]

    assert 'placeholder="Sélectionner une source à gérer"' in block
    assert 'self.owner.selected_notification = int(selector.values[0])' in block
    assert 'label="Modifier"' in block
    assert 'label="Tester"' in block
    assert 'disabled=not has_selection' in block
    assert 'DELETE FROM social_notification_state WHERE subscription_id=?' in block


def test_notification_manager_panel_shows_selected_source_details():
    source = (ROOT / "cogs" / "setup_v2_ui.py").read_text(encoding="utf-8")

    assert 'title="Gestion des sources"' in source
    assert "**Source sélectionnée · #" in source
    assert "**Plateforme**" in source
    assert "**Salon**" in source
    assert "**Rôle pingé**" in source
    assert "**État**" in source


def test_notification_edit_rebaselines_content_instead_of_false_alerting():
    source = (ROOT / "cogs" / "setup_v2_ui.py").read_text(encoding="utf-8")

    modal_start = source.index("class NotificationSourceModal")
    draft_start = source.index("class NotificationDraftView", modal_start)
    modal = source[modal_start:draft_start]

    assert "last_item_id=?, last_item_url=?, last_checked_at=?" in modal
    assert "DELETE FROM social_notification_state WHERE subscription_id=?" in modal
    assert "self.url.default" in modal
