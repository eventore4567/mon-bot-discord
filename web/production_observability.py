"""Observabilité production sûre pour /health.

Cette couche ne crée aucune route et n'expose aucun nom de commande, identifiant de serveur,
traceback ou secret. Elle agrège uniquement les métriques déjà collectées par
ProductionPhaseRuntime afin que le healthcheck externe distingue disponibilité, dégradation
et métriques périmées sans transformer SQLite en base time-series.
"""
from __future__ import annotations

import math
import time
from typing import Any


SLO_WINDOW_SECONDS = 24 * 60 * 60
COMMAND_WINDOW_SECONDS = 24 * 60 * 60
STALE_SAMPLE_SECONDS = 15 * 60
MAX_SLO_SAMPLES = 320


def _value(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        value = getattr(row, key, default)
    return default if value is None else value


def percentile(values: list[float], percent: float) -> float:
    """Percentile interpolé, déterministe et sans dépendance externe."""
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    bounded = min(100.0, max(0.0, float(percent)))
    position = (len(ordered) - 1) * bounded / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _rounded(value: Any, digits: int = 1) -> float:
    try:
        return round(float(value or 0.0), digits)
    except (TypeError, ValueError):
        return 0.0


def _latency_percentiles(rows: list[Any], key: str) -> dict[str, float]:
    values = [_rounded(_value(row, key), 3) for row in rows]
    values = [value for value in values if value >= 0.0]
    return {
        "p50_ms": _rounded(percentile(values, 50), 1),
        "p95_ms": _rounded(percentile(values, 95), 1),
        "p99_ms": _rounded(percentile(values, 99), 1),
        "max_ms": _rounded(max(values) if values else 0.0, 1),
    }


async def _command_window(db: Any, since: int) -> dict[str, Any]:
    row = await db.fetchone(
        "SELECT COALESCE(SUM(calls),0) AS calls, COALESCE(SUM(errors),0) AS errors, "
        "COALESCE(SUM(total_ms),0) AS total_ms, COALESCE(MAX(max_ms),0) AS max_ms "
        "FROM production_command_metrics WHERE hour_bucket >= ?",
        (int(since),),
    )
    calls = int(_value(row, "calls", 0) or 0)
    errors = int(_value(row, "errors", 0) or 0)
    total_ms = float(_value(row, "total_ms", 0.0) or 0.0)
    return {
        "calls": calls,
        "errors": errors,
        "error_rate_pct": round((errors / calls * 100.0) if calls else 0.0, 2),
        "avg_ms": round((total_ms / calls) if calls else 0.0, 1),
        "max_ms": _rounded(_value(row, "max_ms", 0.0), 1),
    }


async def build_runtime_snapshot(bot: Any, *, timestamp: int | None = None) -> dict[str, Any]:
    """Construit un résumé public sans détails sensibles.

    Toute erreur de lecture rend l'observabilité indisponible sans casser /health : le
    healthcheck de disponibilité reste indépendant de la télémétrie historique.
    """
    db = getattr(bot, "db", None)
    if db is None or not callable(getattr(db, "fetchone", None)):
        return {"available": False, "reason": "metrics_unavailable"}

    current = int(time.time() if timestamp is None else timestamp)
    since = current - SLO_WINDOW_SECONDS
    try:
        latest = await db.fetchone(
            "SELECT loop_lag_ms, discord_latency_ms, db_latency_ms, rss_mb, pending_tasks, "
            "postgres_ok, redis_ok, created_at FROM production_slo_samples "
            "ORDER BY created_at DESC LIMIT 1"
        )
        if latest is None:
            return {"available": False, "reason": "no_samples_yet"}

        rows = await db.fetchall(
            "SELECT loop_lag_ms, discord_latency_ms, db_latency_ms, created_at "
            "FROM production_slo_samples WHERE created_at >= ? "
            "ORDER BY created_at DESC LIMIT ?",
            (since, MAX_SLO_SAMPLES),
        )
        rows = list(rows or [])
        states = await db.fetchall(
            "SELECT key, status, updated_at FROM production_slo_state "
            "WHERE status != 'healthy' ORDER BY key"
        )
        degraded = [str(_value(row, "key", "unknown"))[:80] for row in (states or [])]
        created_at = int(_value(latest, "created_at", current) or current)
        sample_age = max(0, current - created_at)
        stale = sample_age > STALE_SAMPLE_SECONDS

        commands_1h = await _command_window(db, current - 3600)
        commands_24h = await _command_window(db, current - COMMAND_WINDOW_SECONDS)

        runtime_status = "stale" if stale else ("degraded" if degraded else "healthy")
        return {
            "available": True,
            "status": runtime_status,
            "sample_age_seconds": sample_age,
            "degraded_components": degraded,
            "current": {
                "event_loop_lag_ms": _rounded(_value(latest, "loop_lag_ms"), 1),
                "discord_latency_ms": _rounded(_value(latest, "discord_latency_ms"), 1),
                "database_latency_ms": _rounded(_value(latest, "db_latency_ms"), 1),
                "rss_mb": _rounded(_value(latest, "rss_mb"), 1),
                "pending_tasks": int(_value(latest, "pending_tasks", 0) or 0),
                "postgres_ok": bool(_value(latest, "postgres_ok", 0)),
                "redis_ok": bool(_value(latest, "redis_ok", 0)),
            },
            "rolling_24h": {
                "samples": len(rows),
                "event_loop": _latency_percentiles(rows, "loop_lag_ms"),
                "discord": _latency_percentiles(rows, "discord_latency_ms"),
                "database": _latency_percentiles(rows, "db_latency_ms"),
            },
            "commands": {
                "last_hour": commands_1h,
                "last_24h": commands_24h,
            },
        }
    except Exception:
        return {"available": False, "reason": "metrics_read_failed"}
