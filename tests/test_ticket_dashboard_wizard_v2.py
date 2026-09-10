from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "web" / "ticket_ping_dashboard.py"


def source() -> str:
    return SOURCE_PATH.read_text(encoding="utf-8")


def test_ticket_dashboard_layer_compiles():
    text = source()
    ast.parse(text, filename=str(SOURCE_PATH))


def test_ticket_editor_has_requested_four_step_flow():
    text = source()
    for label in ("1. Général", "2. Équipe", "3. Panel", "4. Publication"):
        assert label in text
    assert 'data-sx-wizard-button="general"' in text
    assert 'data-sx-wizard-button="team"' in text
    assert 'data-sx-wizard-button="panel"' in text
    assert 'data-sx-wizard-button="publication"' in text


def test_publication_uses_existing_panel_and_does_not_recreate_ticket_data():
    text = source()
    assert 'UPDATE ticket_panels_v2 SET channel_id=?, message_id=?' in text
    assert 'DELETE FROM tickets' not in text
    assert 'DELETE FROM ticket_answers' not in text
    assert 'DELETE FROM ticket_form_questions' not in text
    assert 'TicketPanelView(panel, types)' in text


def test_publication_validates_discord_channel_permissions():
    text = source()
    assert "permissions.view_channel" in text
    assert "permissions.send_messages" in text
    assert "permissions.embed_links" in text
    assert "Ajoutez au moins un type de ticket avant de publier le panel." in text


def test_publication_api_is_csrf_protected_and_manageable_guild_scoped():
    text = source()
    assert "dashboard._manageable_guild(request, guild_id)" in text
    assert "dashboard._require_csrf(request, session)" in text
    assert 'ticket-center/panels/{panel_id}/publication' in text
    assert 'ticket-center/panels/{panel_id}/publish' in text


def test_advanced_global_ping_remains_available_without_cluttering_main_flow():
    text = source()
    assert "Réglage avancé — ping de secours" in text
    assert "/ticket-ping-role" in text
    assert "Utilisé uniquement comme fallback" in text
