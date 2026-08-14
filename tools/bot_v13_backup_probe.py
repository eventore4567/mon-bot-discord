"""Functional round-trip probe for the exact V13 SQLite backup helper functions."""
from __future__ import annotations

import ast
import gzip
import hashlib
import shutil
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V13 = ROOT / "cogs" / "bot_v13_production.py"
HELPERS = {"_sqlite_integrity", "_sqlite_snapshot", "_gzip_file", "_gunzip_file", "_sha256_file"}


def load_helpers() -> dict:
    tree = ast.parse(V13.read_text(encoding="utf-8"), filename=str(V13))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in HELPERS]
    found = {node.name for node in selected}
    if found != HELPERS:
        raise AssertionError(f"Missing V13 helper(s): {sorted(HELPERS - found)}")
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"Path": Path, "sqlite3": sqlite3, "gzip": gzip, "hashlib": hashlib, "shutil": shutil}
    exec(compile(module, str(V13), "exec"), namespace)
    return namespace


def main() -> None:
    helpers = load_helpers()
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

        helpers["_sqlite_snapshot"](live, snapshot)
        assert helpers["_sqlite_integrity"](snapshot) == "ok"
        helpers["_gzip_file"](snapshot, archive)
        digest = helpers["_sha256_file"](archive)
        assert len(digest) == 64 and digest == hashlib.sha256(archive.read_bytes()).hexdigest()
        helpers["_gunzip_file"](archive, restored)
        assert helpers["_sqlite_integrity"](restored) == "ok"

        with sqlite3.connect(restored) as conn:
            rows = conn.execute("SELECT value FROM proof ORDER BY id").fetchall()
        assert rows == [("alpha",), ("beta",), ("gamma",)]

    print("Bot V13 SQLite backup/recovery probe: OK")


if __name__ == "__main__":
    main()
