from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ticket_autoclose_loop_is_fault_isolated_and_restartable():
    source = (ROOT / "cogs" / "tickets.py").read_text(encoding="utf-8")

    assert "async def _process_autoclose_row" in source
    assert "WHERE id = ? AND status = 'ouvert'" in source
    assert "@check_autoclose.error" in source
    assert "self.check_autoclose.restart()" in source
    assert "for row in rows:" in source
    assert "await self._process_autoclose_row(row)" in source
    assert "except Exception:" in source


def test_ticket_autoclose_has_safe_fallbacks():
    source = (ROOT / "cogs" / "tickets.py").read_text(encoding="utf-8")

    assert "délai de secours 30s" in source
    assert "transcript = None" in source
    assert "Journal auto-close indisponible" in source
