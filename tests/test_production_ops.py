from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import unittest
from collections import deque
from pathlib import Path
from unittest import mock

from cogs import production_ops


class _DB:
    def __init__(self, path: str):
        self.path = path


class _Bot:
    def __init__(self, path: str):
        self.db = _DB(path)


class ProductionOpsTests(unittest.TestCase):
    def test_verified_backup_is_readable_and_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "bot.db"
            with sqlite3.connect(source) as conn:
                conn.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)")
                conn.execute("INSERT INTO sample(value) VALUES ('ok')")
                conn.commit()

            backup = root / "backups" / "sentrix-20260821-000000.sqlite3"
            production_ops._create_sqlite_backup_sync(source, backup)
            self.assertTrue(backup.exists())
            ok, detail = production_ops._sqlite_integrity(backup)
            self.assertTrue(ok, detail)
            with sqlite3.connect(backup) as conn:
                self.assertEqual(conn.execute("SELECT value FROM sample").fetchone()[0], "ok")

    def test_backup_directory_defaults_next_to_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "data" / "bot.db"
            bot = _Bot(str(source))
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("SENTRIX_BACKUP_DIR", None)
                self.assertEqual(production_ops._backup_dir(bot), source.parent / "backups")

    def test_health_alert_ignores_user_errors(self):
        bot = _Bot("unused.db")
        bot._sentrix_observability_v26 = {
            "errors": deque(
                [
                    {"type": "CommandNotFound", "at": int(time.time())},
                    {"type": "BadArgument", "at": int(time.time())},
                    {"type": "CommandOnCooldown", "at": int(time.time())},
                ],
                maxlen=80,
            ),
            "slow_commands": deque(maxlen=80),
            "slow_db": deque(maxlen=80),
        }
        key, detail = production_ops._health_alert(bot)
        self.assertIsNone(key)
        self.assertIsNone(detail)

    def test_health_alert_triggers_on_repeated_technical_errors(self):
        bot = _Bot("unused.db")
        now = int(time.time())
        bot._sentrix_observability_v26 = {
            "errors": deque(
                [{"type": "RuntimeError", "at": now} for _ in range(5)],
                maxlen=80,
            ),
            "slow_commands": deque(maxlen=80),
            "slow_db": deque(maxlen=80),
        }
        with mock.patch.dict(os.environ, {"SENTRIX_ALERT_ERROR_THRESHOLD": "5"}, clear=False):
            key, detail = production_ops._health_alert(bot)
        self.assertTrue(str(key).startswith("errors:"))
        self.assertIn("5 erreurs techniques", str(detail))

    def test_health_alert_never_uses_observability_message_content(self):
        bot = _Bot("unused.db")
        now = int(time.time())
        bot._sentrix_observability_v26 = {
            "errors": deque(
                [
                    {
                        "type": "RuntimeError",
                        "at": now,
                        "message": "SECRET USER CONTENT",
                    }
                    for _ in range(5)
                ],
                maxlen=80,
            ),
            "slow_commands": deque(maxlen=80),
            "slow_db": deque(maxlen=80),
        }
        key, detail = production_ops._health_alert(bot)
        self.assertIsNotNone(key)
        self.assertNotIn("SECRET USER CONTENT", str(detail))


if __name__ == "__main__":
    unittest.main()
