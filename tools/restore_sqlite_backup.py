"""Offline restore tool for SentriX SQLite backups.

Usage (bot MUST be stopped):
    python tools/restore_sqlite_backup.py backups/sentrix-YYYYmmdd-HHMMSS.sqlite3 --confirm-stopped

The tool verifies the backup, creates a safety copy of the current database, restores via
an atomic os.replace(), then verifies the restored database again. It never touches Discord.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path


def integrity(path: Path) -> tuple[bool, str]:
    try:
        with sqlite3.connect(str(path), timeout=10) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        result = str(row[0] if row else "unknown")
        return result.casefold() == "ok", result
    except Exception as exc:
        return False, type(exc).__name__


def default_database_path() -> Path:
    raw = os.getenv("DATABASE_PATH", "database/bot.db")
    return Path(raw).expanduser().resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore a verified SentriX SQLite backup.")
    parser.add_argument("backup", type=Path)
    parser.add_argument("--database", type=Path, default=default_database_path())
    parser.add_argument(
        "--confirm-stopped",
        action="store_true",
        help="Required acknowledgement that every SentriX process using the DB is stopped.",
    )
    args = parser.parse_args()

    if not args.confirm_stopped:
        print("REFUSED: stop SentriX first, then rerun with --confirm-stopped.", file=sys.stderr)
        return 2

    backup = args.backup.expanduser().resolve()
    target = args.database.expanduser().resolve()
    if not backup.is_file():
        print(f"REFUSED: backup does not exist: {backup}", file=sys.stderr)
        return 2

    ok, detail = integrity(backup)
    if not ok:
        print(f"REFUSED: backup integrity_check failed: {detail}", file=sys.stderr)
        return 3

    target.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    safety = target.with_name(f"{target.name}.pre-restore-{timestamp}.bak")
    if target.exists():
        shutil.copy2(target, safety)
        safety_ok, safety_detail = integrity(safety)
        if not safety_ok:
            safety.unlink(missing_ok=True)
            print(f"REFUSED: current DB safety copy failed integrity_check: {safety_detail}", file=sys.stderr)
            return 4

    temp = target.with_suffix(target.suffix + ".restore.tmp")
    temp.unlink(missing_ok=True)
    try:
        shutil.copy2(backup, temp)
        copied_ok, copied_detail = integrity(temp)
        if not copied_ok:
            print(f"REFUSED: copied backup failed integrity_check: {copied_detail}", file=sys.stderr)
            return 5
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)

    restored_ok, restored_detail = integrity(target)
    if not restored_ok:
        print(f"ERROR: restored DB failed integrity_check: {restored_detail}", file=sys.stderr)
        if safety.exists():
            os.replace(safety, target)
            print("Safety database restored automatically.", file=sys.stderr)
        return 6

    print(f"OK: restored {backup} -> {target}")
    if safety.exists():
        print(f"Safety copy kept at: {safety}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
