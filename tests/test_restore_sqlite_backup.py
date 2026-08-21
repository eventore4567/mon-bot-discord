from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESTORE_TOOL = ROOT / "tools" / "restore_sqlite_backup.py"


def _make_db(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS marker(value TEXT)")
        conn.execute("DELETE FROM marker")
        conn.execute("INSERT INTO marker(value) VALUES (?)", (value,))
        conn.commit()


def _read_value(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT value FROM marker LIMIT 1").fetchone()
    return str(row[0])


class RestoreSQLiteBackupTests(unittest.TestCase):
    def test_restore_requires_explicit_stopped_acknowledgement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = root / "backup.sqlite3"
            target = root / "bot.db"
            _make_db(backup, "backup")
            _make_db(target, "current")
            result = subprocess.run(
                [sys.executable, str(RESTORE_TOOL), str(backup), "--database", str(target)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(_read_value(target), "current")

    def test_restore_replaces_database_and_keeps_safety_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = root / "backup.sqlite3"
            target = root / "bot.db"
            _make_db(backup, "from-backup")
            _make_db(target, "before-restore")

            result = subprocess.run(
                [
                    sys.executable,
                    str(RESTORE_TOOL),
                    str(backup),
                    "--database",
                    str(target),
                    "--confirm-stopped",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(_read_value(target), "from-backup")
            safety = list(root.glob("bot.db.pre-restore-*.bak"))
            self.assertEqual(len(safety), 1)
            self.assertEqual(_read_value(safety[0]), "before-restore")


if __name__ == "__main__":
    unittest.main()
