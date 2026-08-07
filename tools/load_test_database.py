"""Benchmark de charge REEL de la couche SQLite de SentriX.

Ce script crée une base TEMPORAIRE et utilise la vraie classe Database du bot.
Il ne touche jamais à la base Railway/production et n'envoie aucune requête Discord.

Exemples:
  python tools/load_test_database.py --users 200 --operations 50000
  python tools/load_test_database.py --users 1000 --operations 200000
"""
from __future__ import annotations

import argparse
import asyncio
import math
import os
import random
import statistics
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.db import Database


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    rank = (len(values) - 1) * p
    lo, hi = math.floor(rank), math.ceil(rank)
    if lo == hi:
        return values[lo]
    frac = rank - lo
    return values[lo] * (1 - frac) + values[hi] * frac


OPS = (
    ("config-cache-read", 0.20),
    ("config-cold-read", 0.05),
    ("automod-read", 0.15),
    ("economy-read", 0.20),
    ("economy-write", 0.15),
    ("automod-log-write", 0.15),
    ("ticket-write", 0.05),
    ("ticket-read", 0.05),
)


def choose_op() -> str:
    value = random.random()
    total = 0.0
    for name, weight in OPS:
        total += weight
        if value <= total:
            return name
    return OPS[-1][0]


async def run(users: int, operations: int, seed: int) -> dict:
    random.seed(seed)
    guild_count = max(5, min(50, users // 20 or 5))
    guild_ids = [10_000_000 + i for i in range(guild_count)]
    member_ids = [20_000_000 + i for i in range(max(users * 2, 1000))]

    with tempfile.TemporaryDirectory(prefix="sentrix-db-load-") as tmp:
        db_path = os.path.join(tmp, "benchmark.sqlite3")
        db = Database(db_path)
        await db.connect()

        # Préparation hors mesure : plusieurs serveurs et utilisateurs, comme en prod.
        for guild_id in guild_ids:
            await db.ensure_guild(guild_id)
        await db._conn.executemany(
            "INSERT OR IGNORE INTO economy (guild_id, user_id, cash, bank) VALUES (?, ?, ?, ?)",
            [
                (guild_ids[i % guild_count], user_id, 1000, 500)
                for i, user_id in enumerate(member_ids)
            ],
        )
        await db._conn.commit()

        queue: asyncio.Queue[tuple[int, float] | None] = asyncio.Queue(maxsize=max(users * 4, 1000))
        latencies: list[float] = []
        service_times: list[float] = []
        errors: Counter[str] = Counter()
        counts: Counter[str] = Counter()
        result_lock = asyncio.Lock()

        async def do_operation(name: str, guild_id: int, user_id: int) -> None:
            if name == "config-cache-read":
                await db.get_guild_config(guild_id)
            elif name == "config-cold-read":
                db.invalidate_guild_config(guild_id)
                await db.get_guild_config(guild_id)
            elif name == "automod-read":
                await db.get_automod(guild_id)
            elif name == "economy-read":
                await db.fetchone(
                    "SELECT cash, bank FROM economy WHERE guild_id = ? AND user_id = ?",
                    (guild_id, user_id),
                )
            elif name == "economy-write":
                await db.execute(
                    "INSERT INTO economy (guild_id, user_id, cash, bank) VALUES (?, ?, 1, 0) "
                    "ON CONFLICT(guild_id, user_id) DO UPDATE SET cash = cash + 1",
                    (guild_id, user_id),
                )
            elif name == "automod-log-write":
                await db.log_automod_action(
                    guild_id, user_id, "load_test", "suppression", "benchmark local"
                )
            elif name == "ticket-write":
                now = int(time.time())
                await db.execute(
                    "INSERT INTO tickets (guild_id, channel_id, user_id, status, created_at, last_activity_at) "
                    "VALUES (?, ?, ?, 'ouvert', ?, ?)",
                    (guild_id, random.randint(30_000_000, 99_999_999), user_id, now, now),
                )
            elif name == "ticket-read":
                await db.fetchone(
                    "SELECT id, status, claimed_by FROM tickets WHERE guild_id = ? "
                    "ORDER BY id DESC LIMIT 1",
                    (guild_id,),
                )

        async def worker() -> None:
            while True:
                item = await queue.get()
                if item is None:
                    queue.task_done()
                    return
                _, queued_at = item
                name = choose_op()
                guild_id = random.choice(guild_ids)
                user_id = random.choice(member_ids)
                started = time.perf_counter()
                try:
                    await do_operation(name, guild_id, user_id)
                except Exception as exc:  # le rapport doit montrer TOUTE contention réelle
                    error_name = f"{type(exc).__name__}: {str(exc)[:120]}"
                    async with result_lock:
                        errors[error_name] += 1
                finished = time.perf_counter()
                async with result_lock:
                    counts[name] += 1
                    service_times.append((finished - started) * 1000)
                    latencies.append((finished - queued_at) * 1000)
                queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(users)]
        started_at = time.perf_counter()
        for operation_id in range(operations):
            await queue.put((operation_id, time.perf_counter()))
        await queue.join()
        duration = time.perf_counter() - started_at

        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)

        integrity = await db.fetchone("PRAGMA integrity_check")
        ticket_count = await db.fetchone("SELECT COUNT(*) AS c FROM tickets")
        log_count = await db.fetchone("SELECT COUNT(*) AS c FROM automod_logs")
        await db.close()

    return {
        "users": users,
        "operations": operations,
        "duration": duration,
        "throughput": operations / duration if duration else 0.0,
        "errors": sum(errors.values()),
        "error_details": errors,
        "counts": counts,
        "avg": statistics.fmean(latencies) if latencies else 0.0,
        "p50": percentile(latencies, 0.50),
        "p95": percentile(latencies, 0.95),
        "p99": percentile(latencies, 0.99),
        "service_avg": statistics.fmean(service_times) if service_times else 0.0,
        "service_p95": percentile(service_times, 0.95),
        "integrity": integrity[0] if integrity else "unknown",
        "tickets": int(ticket_count["c"]) if ticket_count else 0,
        "automod_logs": int(log_count["c"]) if log_count else 0,
    }


def report(r: dict) -> None:
    print("\n=== SENTRIX — REAL SQLITE LOAD TEST ===")
    print(f"Utilisateurs virtuels : {r['users']:,}".replace(",", " "))
    print(f"Opérations réelles     : {r['operations']:,}".replace(",", " "))
    print(f"Durée                  : {r['duration']:.2f} s")
    print(f"Débit SQLite           : {r['throughput']:,.0f} op/s".replace(",", " "))
    print(f"Erreurs                : {r['errors']} ({r['errors'] / r['operations'] * 100:.4f} %)")
    print(f"Intégrité SQLite       : {r['integrity']}")
    print("\nLatence totale")
    print(f"  moyenne : {r['avg']:.2f} ms")
    print(f"  p50     : {r['p50']:.2f} ms")
    print(f"  p95     : {r['p95']:.2f} ms")
    print(f"  p99     : {r['p99']:.2f} ms")
    print("\nTraitement DB")
    print(f"  moyenne : {r['service_avg']:.2f} ms")
    print(f"  p95     : {r['service_p95']:.2f} ms")
    print("\nRépartition")
    for name, count in sorted(r["counts"].items()):
        print(f"  {name:<22} {count:>9}")
    print(f"\nTickets écrits : {r['tickets']}")
    print(f"Logs AutoMod    : {r['automod_logs']}")
    if r["error_details"]:
        print("\nErreurs rencontrées")
        for error, count in r["error_details"].most_common(10):
            print(f"  {count:>6} × {error}")
    print("\nSECURITE : base temporaire uniquement — aucune donnée Railway/Discord utilisée.")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Benchmark réel de la base SQLite SentriX")
    p.add_argument("--users", type=int, default=200)
    p.add_argument("--operations", type=int, default=50000)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    if not 1 <= args.users <= 5000:
        p.error("--users doit être compris entre 1 et 5000")
    if not 1 <= args.operations <= 1_000_000:
        p.error("--operations doit être compris entre 1 et 1000000")
    return args


if __name__ == "__main__":
    args = parse_args()
    result = asyncio.run(run(args.users, args.operations, args.seed))
    report(result)
