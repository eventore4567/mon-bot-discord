from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bulk_delete_skips_each_purged_message_individually():
    source = (ROOT / "cogs" / "logs.py").read_text(encoding="utf-8")

    assert "for message_id in payload.message_ids:" in source
    assert "if log_service.is_purged(message_id):" in source
    assert "continue" in source


def test_bulk_delete_isolates_failures_per_message():
    source = (ROOT / "cogs" / "logs.py").read_text(encoding="utf-8")

    assert "Journal bulk delete impossible" in source
    assert "except Exception:" in source
