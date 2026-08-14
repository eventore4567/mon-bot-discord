"""Functional round-trip probe for Bot V13 SQLite backup helpers."""
from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V13 = ROOT / "cogs" / "bot_v13_production.py"


def load_v13_module():
    spec = importlib.util.spec_from_file_location("sentrix_bot_v13_probe", V13)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load Bot V13 module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    v13 = load_v13_module()
    with tempfile.TemporaryDirectory(prefix="sentrix-v13-") as tmp:
        root = Path(tmp)
        live = root / "live.db"
        snapshot = root / "snapshot.db"
        archive = root / "snapshot.db.gz"
        restored = root / "restored.db"

        with sqlite3.connect(live) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE proof (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
            conn.executemany("INSERT INTO proof(value) VALUES (?)", [("alpha",), ("beta",), ("gamma",)])
            conn.commit()

        v13._sqlite_snapshot(live, snapshot)
        assert v13._sqlite_integrity(snapshot) == "ok"
        v13._gzip_file(snapshot, archive)
        digest = v13._sha256_file(archive)
        assert len(digest) == 64 and digest == hashlib.sha256(archive.read_bytes()).hexdigest()
        v13._gunzip_file(archive, restored)
        assert v13._sqlite_integrity(restored) == "ok"

        with sqlite3.connect(restored) as conn:
            rows = conn.execute("SELECT value FROM proof ORDER BY id").fetchall()
        assert rows == [("alpha",), ("beta",), ("gamma",)]

    print("Bot V13 SQLite backup/recovery probe: OK")


if __name__ == "__main__":
    main()
