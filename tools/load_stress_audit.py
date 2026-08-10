#!/usr/bin/env python3
"""Petit test de charge reproductible pour détecter les régressions DB avant production."""
from __future__ import annotations

import asyncio
import pathlib
import sqlite3
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.db import Database
from utils.durable_database import _backup_sqlite_sync, _sqlite_healthy_sync


async def main() -> None:
    path = pathlib.Path("/tmp/sentrix-load-stress.db")
    path.unlink(missing_ok=True)
    db = Database(str(path))
    await db.connect()
    started = time.perf_counter()
    try:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS load_probe (id INTEGER PRIMARY KEY AUTOINCREMENT, worker INTEGER NOT NULL, seq INTEGER NOT NULL, payload TEXT NOT NULL)"
        )

        async def writer(worker: int) -> None:
            for seq in range(50):
                await db.execute(
                    "INSERT INTO load_probe (worker,seq,payload) VALUES (?,?,?)",
                    (worker, seq, f"sentrix-{worker}-{seq}" * 4),
                )

        # 20 producteurs concurrents, 1000 commits au total.
        await asyncio.wait_for(asyncio.gather(*(writer(i) for i in range(20))), timeout=35)
        row = await db.fetchone("SELECT COUNT(*) AS n FROM load_probe")
        assert int(row["n"]) == 1000, row["n"]

        async def reader(index: int) -> int:
            row = await db.fetchone("SELECT COUNT(*) AS n FROM load_probe WHERE worker=?", (index % 20,))
            return int(row["n"])

        results = await asyncio.wait_for(asyncio.gather(*(reader(i) for i in range(200))), timeout=10)
        assert results and all(value == 50 for value in results)
        check = await db.fetchone("PRAGMA quick_check")
        assert check and str(check[0]).casefold() == "ok"
    finally:
        await db.close()

    # Vérifie aussi le mécanisme utilisé pour les snapshots PostgreSQL sans nécessiter
    # un vrai PostgreSQL dans la CI.
    with tempfile.TemporaryDirectory() as folder:
        snapshot = pathlib.Path(folder) / "snapshot.db"
        size = await asyncio.to_thread(_backup_sqlite_sync, path, snapshot)
        assert size > 4096
        assert await asyncio.to_thread(_sqlite_healthy_sync, snapshot)
        conn = sqlite3.connect(str(snapshot))
        try:
            count = conn.execute("SELECT COUNT(*) FROM load_probe").fetchone()[0]
        finally:
            conn.close()
        assert count == 1000

    elapsed = time.perf_counter() - started
    assert elapsed < 45, f"Test de charge trop lent: {elapsed:.2f}s"
    print(f"OK: 1000 écritures + 200 lectures concurrentes, snapshot cohérent, {elapsed:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
