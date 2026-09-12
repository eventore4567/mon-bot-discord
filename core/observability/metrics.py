"""Compteurs et latences en mémoire, par commande (+ transport en interne).

Pas de dépendance à Discord ni à la base de données : c'est un état de
processus, redémarré à chaque déploiement, exactement comme les autres
agrégats "depuis le dernier redémarrage" déjà utilisés ailleurs dans SentriX
(``production_phase_runtime.py``). Suffisant pour la Phase 1 (diagnostic en
direct) ; une persistance viendrait d'une phase ultérieure si le besoin est
confirmé.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

_MAX_SAMPLES = 500
_RECENT_FAILURE_WINDOW_SECONDS = 300.0


@dataclass
class _Bucket:
    count: int = 0
    success_count: int = 0
    failure_count: int = 0
    latencies_ms: deque = field(default_factory=lambda: deque(maxlen=_MAX_SAMPLES))
    failure_timestamps: deque = field(default_factory=lambda: deque(maxlen=_MAX_SAMPLES))


_stats: dict[tuple[str, str], _Bucket] = {}


def _bucket(command: str, transport: str) -> _Bucket:
    key = (command, transport)
    bucket = _stats.get(key)
    if bucket is None:
        bucket = _Bucket()
        _stats[key] = bucket
    return bucket


def record(command: str, transport: str, latency_ms: float, *, success: bool) -> None:
    bucket = _bucket(command, transport)
    bucket.count += 1
    if success:
        bucket.success_count += 1
        bucket.latencies_ms.append(max(0.0, float(latency_ms)))
    else:
        bucket.failure_count += 1
        bucket.failure_timestamps.append(time.time())


def record_error(command: str, transport: str) -> None:
    """Alias pour un appelant qui n'a pas de latence utile à rapporter."""
    record(command, transport, 0.0, success=False)


def _percentile(sorted_samples: list[float], pct: float) -> float:
    if not sorted_samples:
        return 0.0
    if len(sorted_samples) == 1:
        return sorted_samples[0]
    index = min(len(sorted_samples) - 1, max(0, round(pct * (len(sorted_samples) - 1))))
    return sorted_samples[index]


@dataclass
class CommandStats:
    command: str
    count: int
    success_count: int
    failure_count: int
    success_rate: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    recent_failures: int


def snapshot(command: str | None = None) -> dict[str, CommandStats]:
    """Statistiques agrégées par commande, transports fusionnés.

    ``command`` filtre sur une commande précise ; laissé à ``None``, retourne
    tout ce qui a été observé depuis le dernier redémarrage du processus.
    """
    merged: dict[str, list[_Bucket]] = {}
    for (cmd, _transport), bucket in _stats.items():
        if command is not None and cmd != command:
            continue
        merged.setdefault(cmd, []).append(bucket)

    now = time.time()
    result: dict[str, CommandStats] = {}
    for cmd, buckets in merged.items():
        count = sum(b.count for b in buckets)
        success_count = sum(b.success_count for b in buckets)
        failure_count = sum(b.failure_count for b in buckets)
        latencies = sorted(v for b in buckets for v in b.latencies_ms)
        recent_failures = sum(
            1
            for b in buckets
            for ts in b.failure_timestamps
            if now - ts <= _RECENT_FAILURE_WINDOW_SECONDS
        )
        result[cmd] = CommandStats(
            command=cmd,
            count=count,
            success_count=success_count,
            failure_count=failure_count,
            success_rate=(success_count / count) if count else 0.0,
            p50_ms=_percentile(latencies, 0.50),
            p95_ms=_percentile(latencies, 0.95),
            p99_ms=_percentile(latencies, 0.99),
            recent_failures=recent_failures,
        )
    return result


def reset_for_tests() -> None:
    _stats.clear()
