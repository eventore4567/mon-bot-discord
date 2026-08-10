#!/usr/bin/env python3
"""Audit déterministe de l'observabilité production SentriX V2."""
from __future__ import annotations

import asyncio
import pathlib
import sys
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.production_observability import build_runtime_snapshot, percentile


NOW = 2_000_000_000


class FakeDB:
    async def fetchone(self, query: str, params=()):
        if "FROM production_slo_samples" in query:
            return {
                "loop_lag_ms": 12.0,
                "discord_latency_ms": 42.0,
                "db_latency_ms": 3.5,
                "rss_mb": 128.0,
                "pending_tasks": 27,
                "postgres_ok": 1,
                "redis_ok": 1,
                "created_at": NOW - 60,
            }
        if "FROM production_command_metrics" in query:
            since = int(params[0])
            if since >= NOW - 3600:
                return {"calls": 100, "errors": 2, "total_ms": 4500.0, "max_ms": 210.0}
            return {"calls": 1000, "errors": 15, "total_ms": 60000.0, "max_ms": 900.0}
        raise AssertionError(f"Requête fetchone inattendue: {query}")

    async def fetchall(self, query: str, params=()):
        if "FROM production_slo_samples" in query:
            return [
                {"loop_lag_ms": 1.0, "discord_latency_ms": 20.0, "db_latency_ms": 2.0, "created_at": NOW - 1200},
                {"loop_lag_ms": 2.0, "discord_latency_ms": 30.0, "db_latency_ms": 3.0, "created_at": NOW - 900},
                {"loop_lag_ms": 3.0, "discord_latency_ms": 40.0, "db_latency_ms": 4.0, "created_at": NOW - 600},
                {"loop_lag_ms": 4.0, "discord_latency_ms": 50.0, "db_latency_ms": 5.0, "created_at": NOW - 300},
                {"loop_lag_ms": 5.0, "discord_latency_ms": 60.0, "db_latency_ms": 6.0, "created_at": NOW - 60},
            ]
        if "FROM production_slo_state" in query:
            return [{"key": "discord", "status": "degraded", "updated_at": NOW - 30}]
        raise AssertionError(f"Requête fetchall inattendue: {query}")


class BrokenDB:
    async def fetchone(self, *_args, **_kwargs):
        raise RuntimeError("sensitive database detail")


async def main_audit() -> None:
    assert percentile([], 95) == 0.0
    assert percentile([7.0], 99) == 7.0
    assert percentile([1, 2, 3, 4, 5], 50) == 3.0
    assert round(percentile([1, 2, 3, 4, 5], 95), 1) == 4.8

    snapshot = await build_runtime_snapshot(SimpleNamespace(db=FakeDB()), timestamp=NOW)
    assert snapshot["available"] is True
    assert snapshot["status"] == "degraded"
    assert snapshot["sample_age_seconds"] == 60
    assert snapshot["degraded_components"] == ["discord"]
    assert snapshot["current"]["discord_latency_ms"] == 42.0
    assert snapshot["current"]["postgres_ok"] is True
    assert snapshot["rolling_24h"]["samples"] == 5
    assert snapshot["rolling_24h"]["event_loop"]["p50_ms"] == 3.0
    assert snapshot["rolling_24h"]["discord"]["p95_ms"] == 58.0
    assert snapshot["commands"]["last_hour"] == {
        "calls": 100,
        "errors": 2,
        "error_rate_pct": 2.0,
        "avg_ms": 45.0,
        "max_ms": 210.0,
    }
    assert snapshot["commands"]["last_24h"]["calls"] == 1000
    assert snapshot["commands"]["last_24h"]["error_rate_pct"] == 1.5

    serialised = repr(snapshot)
    for forbidden in ("command_name", "guild_id", "user_id", "token", "traceback"):
        assert forbidden not in serialised, f"Champ sensible exposé: {forbidden}"

    broken = await build_runtime_snapshot(SimpleNamespace(db=BrokenDB()), timestamp=NOW)
    assert broken == {"available": False, "reason": "metrics_read_failed"}
    unavailable = await build_runtime_snapshot(SimpleNamespace(db=None), timestamp=NOW)
    assert unavailable == {"available": False, "reason": "metrics_unavailable"}

    stale_db = FakeDB()
    original_fetchone = stale_db.fetchone

    async def stale_fetchone(query: str, params=()):
        row = await original_fetchone(query, params)
        if "FROM production_slo_samples" in query:
            row = dict(row)
            row["created_at"] = NOW - 3600
        return row

    stale_db.fetchone = stale_fetchone
    stale = await build_runtime_snapshot(SimpleNamespace(db=stale_db), timestamp=NOW)
    assert stale["status"] == "stale"

    print("Observability V2: percentiles, agrégats commandes, état SLO et fail-safe validés")
    print("OK: aucune commande, guild, user, trace ou secret n'est exposé par le snapshot public")


if __name__ == "__main__":
    asyncio.run(main_audit())
