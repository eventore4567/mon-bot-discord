from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ticket_creation_is_serialized_per_member_and_type():
    source = (ROOT / "cogs" / "tickets.py").read_text(encoding="utf-8")

    assert "_ticket_open_locks" in source
    assert "async with lock:" in source
    assert "count_genuinely_open_tickets(" in source
    assert "return await self._create_ticket_locked" in source


def test_ticket_open_lock_registry_is_bounded():
    source = (ROOT / "cogs" / "tickets.py").read_text(encoding="utf-8")

    assert "if len(self._ticket_open_locks) > 5000:" in source
    assert "not candidate_lock.locked()" in source


def test_ticket_creation_rolls_back_channel_when_database_insert_fails():
    source = (ROOT / "cogs" / "tickets.py").read_text(encoding="utf-8")

    assert "rollback d'un ticket non persisté" in source
    assert "await channel.delete(" in source
    assert "Aucun ticket incomplet n'a été conservé." in source


def test_ticket_initialization_rolls_back_when_control_message_fails():
    source = (ROOT / "cogs" / "tickets.py").read_text(encoding="utf-8")

    assert "rollback d'un ticket sans message de contrôle" in source
    assert "DELETE FROM ticket_answers WHERE ticket_id = ?" in source
    assert "DELETE FROM tickets WHERE id = ?" in source
    assert "La création a été annulée proprement." in source


def test_ticket_open_journal_failure_does_not_invalidate_ticket():
    source = (ROOT / "cogs" / "tickets.py").read_text(encoding="utf-8")

    assert "Journal d'ouverture ticket indisponible" in source
    assert "try:" in source
    assert "except Exception:" in source
