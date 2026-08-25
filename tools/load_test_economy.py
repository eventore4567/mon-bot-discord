"""Deterministic local load test for SentriX economy transactions.

No Discord token or network connection is used. The test creates a temporary SQLite DB,
loads balances, then performs concurrent Database.pay_member() transfers. The invariant
checked is simple and important: money must never be duplicated/lost and no wallet can go
negative because of concurrent transfers.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
import tempfile
import time
from pathlib import Path

# `python tools/load_test_economy.py` places tools/ at sys.path[0]. Add the repository root
# explicitly so the smoke test behaves the same locally and in GitHub Actions.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.db import Database


async def _run(users: int, operations: int, concurrency: int) -> tuple[bool, dict]:
    users = max(4, int(users))
    operations = max(1, int(operations))
    concurrency = max(1, min(int(concurrency), operations))

    with tempfile.TemporaryDirectory(prefix="sentrix-load-") as tmp:
        db = Database(str(Path(tmp) / "load.sqlite3"))
        await db.connect()
        guild_id = 987654321
        initial = 50_000
        try:
            for user_id in range(1, users + 1):
                await db.ensure_economy(guild_id, user_id)
                await db.add_balance(guild_id, user_id, initial)

            before_rows = await db.fetchall(
                "SELECT user_id,cash,bank FROM economy WHERE guild_id=? ORDER BY user_id",
                (guild_id,),
            )
            before_total = sum(int(row["cash"] or 0) + int(row["bank"] or 0) for row in before_rows)

            queue: asyncio.Queue[int | None] = asyncio.Queue()
            for index in range(operations):
                queue.put_nowait(index)
            for _ in range(concurrency):
                queue.put_nowait(None)

            successes = 0
            failures = 0
            lock = asyncio.Lock()

            async def worker(worker_id: int) -> None:
                nonlocal successes, failures
                rng = random.Random(20260821 + worker_id)
                while True:
                    marker = await queue.get()
                    try:
                        if marker is None:
                            return
                        sender = rng.randint(1, users)
                        receiver = rng.randint(1, users - 1)
                        if receiver >= sender:
                            receiver += 1
                        amount = rng.randint(1, 100)
                        ok = await db.pay_member(
                            guild_id,
                            sender,
                            receiver,
                            amount,
                            reason="load-test",
                        )
                        async with lock:
                            if ok:
                                successes += 1
                            else:
                                failures += 1
                    finally:
                        queue.task_done()

            started = time.perf_counter()
            tasks = [asyncio.create_task(worker(index)) for index in range(concurrency)]
            await queue.join()
            await asyncio.gather(*tasks)
            elapsed = max(0.000001, time.perf_counter() - started)

            after_rows = await db.fetchall(
                "SELECT user_id,cash,bank FROM economy WHERE guild_id=? ORDER BY user_id",
                (guild_id,),
            )
            after_total = sum(int(row["cash"] or 0) + int(row["bank"] or 0) for row in after_rows)
            negatives = [
                int(row["user_id"])
                for row in after_rows
                if int(row["cash"] or 0) < 0 or int(row["bank"] or 0) < 0
            ]

            ok = before_total == after_total and not negatives
            details = {
                "users": users,
                "operations": operations,
                "concurrency": concurrency,
                "successes": successes,
                "rejected": failures,
                "seconds": round(elapsed, 3),
                "ops_per_second": round(operations / elapsed, 1),
                "before_total": before_total,
                "after_total": after_total,
                "negative_accounts": negatives,
            }
            return ok, details
        finally:
            conn = getattr(db, "_conn", None)
            if conn is not None:
                await conn.close()


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Load-test SentriX atomic economy transfers.")
    parser.add_argument("--users", type=int, default=80)
    parser.add_argument("--operations", type=int, default=1200)
    parser.add_argument("--concurrency", type=int, default=24)
    args = parser.parse_args()

    ok, details = await _run(args.users, args.operations, args.concurrency)
    print("SentriX economy load test")
    for key, value in details.items():
        print(f"{key}: {value}")
    if not ok:
        print("FAILED: money invariant or non-negative balance invariant violated.")
        return 1
    print("OK: atomic transfer invariants preserved under concurrency.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
