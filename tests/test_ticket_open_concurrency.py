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
