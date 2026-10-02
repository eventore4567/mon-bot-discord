"""Projection de santé du registre de modules SentriX."""
from __future__ import annotations

import time
from typing import Mapping

from core.module_state import ModuleState


VALID_STATUSES = frozenset({
    "pending",
    "loading",
    "loaded",
    "failed",
    "blocked",
    "unloaded",
})


def validate_invariants(states: Mapping[str, ModuleState]) -> list[str]:
    problems: list[str] = []
    for name, state in states.items():
        if state.status not in VALID_STATUSES:
            problems.append(f"{name}: statut inconnu {state.status}")
        if state.in_flight < 0:
            problems.append(f"{name}: compteur in-flight négatif")
        if state.critical and state.circuit_open:
            problems.append(f"{name}: circuit ouvert sur module critique")
        if state.status == "loaded" and state.blocked_by:
            problems.append(f"{name}: chargé mais encore bloqué par dépendance")
        if state.in_flight == 0 and state.in_flight_since is not None:
            problems.append(f"{name}: horodatage in-flight sans appel actif")
        if state.in_flight > 0 and state.in_flight_since is None:
            problems.append(f"{name}: appel actif sans horodatage")
    return problems


def build_snapshot(
    states: Mapping[str, ModuleState],
    *,
    recent_events: list[dict],
) -> dict:
    rows = list(states.values())
    failed = [
        {"name": row.name, "error": row.error or "UnknownError", "critical": row.critical}
        for row in rows
        if row.status == "failed"
    ]
    blocked = [
        {"name": row.name, "blocked_by": list(row.blocked_by), "critical": row.critical}
        for row in rows
        if row.status == "blocked"
    ]
    critical_failed = sorted(
        {item["name"] for item in failed if item["critical"]}
        | {item["name"] for item in blocked if item["critical"]}
    )
    runtime_degraded = sorted(
        row.name for row in rows
        if row.status == "loaded" and row.runtime_degraded
    )
    critical_runtime_degraded = sorted(
        row.name for row in rows
        if row.status == "loaded" and row.runtime_degraded and row.critical
    )
    open_circuits = sorted(
        row.name for row in rows
        if row.status == "loaded" and row.circuit_open
    )
    invariant_errors = validate_invariants(states)

    return {
        "expected": len(rows),
        "loaded": sum(row.status == "loaded" for row in rows),
        "failed": failed,
        "blocked": blocked,
        "critical_failed": critical_failed,
        "critical_runtime_degraded": critical_runtime_degraded,
        "ready": not critical_failed and not critical_runtime_degraded and not invariant_errors,
        "invariant_errors": invariant_errors,
        "runtime_degraded": runtime_degraded,
        "open_circuits": open_circuits,
        "recent_events": recent_events,
        "modules": {
            row.name: {
                "status": row.status,
                "critical": row.critical,
                "load_ms": row.load_ms,
                "error": row.error,
                "last_error": row.last_error,
                "attempts": row.attempts,
                "reloads": row.reloads,
                "last_operation": row.last_operation,
                "blocked_by": list(row.blocked_by),
                "runtime_errors": row.runtime_errors,
                "consecutive_runtime_errors": row.consecutive_runtime_errors,
                "runtime_degraded": row.runtime_degraded,
                "circuit_open": row.circuit_open,
                "circuit_opened_at": row.circuit_opened_at,
                "circuit_reason": row.circuit_reason,
                "in_flight": row.in_flight,
                "in_flight_since": row.in_flight_since,
                "in_flight_age_seconds": (
                    max(0, round(time.time() - row.in_flight_since, 2))
                    if row.in_flight and row.in_flight_since is not None
                    else 0
                ),
                "last_runtime_error": row.last_runtime_error,
                "last_runtime_error_at": row.last_runtime_error_at,
            }
            for row in rows
        },
    }
