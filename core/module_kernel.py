"""Micro-kernel SentriX : registre minimal de santé des modules.

Le noyau ne connaît aucune logique métier Discord. Il suit uniquement l'état de
chargement des extensions afin qu'un module optionnel en panne reste isolé et
observable sans rendre tout le bot indisponible.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable, Mapping


@dataclass(slots=True)
class ModuleState:
    name: str
    critical: bool = False
    status: str = "pending"
    load_ms: float | None = None
    error: str | None = None
    last_error: str | None = None
    attempts: int = 0
    reloads: int = 0
    last_operation: str = "startup"
    blocked_by: tuple[str, ...] = ()
    runtime_errors: int = 0
    consecutive_runtime_errors: int = 0
    runtime_degraded: bool = False
    circuit_open: bool = False
    circuit_opened_at: float | None = None
    circuit_reason: str | None = None
    in_flight: int = 0
    in_flight_since: float | None = None
    last_runtime_error: str | None = None
    last_runtime_error_at: float | None = None
    _started_at: float | None = field(default=None, repr=False)

    def begin(self, *, operation: str = "load") -> None:
        self.attempts += 1
        if operation == "reload":
            self.reloads += 1
        self.last_operation = operation
        self.status = "loading"
        self.error = None
        self.blocked_by = ()
        self._started_at = time.perf_counter()

    def finish(self, *, error: BaseException | None = None) -> None:
        if self._started_at is not None:
            self.load_ms = round((time.perf_counter() - self._started_at) * 1000, 2)
        self._started_at = None
        if error is None:
            self.status = "loaded"
            self.error = None
        else:
            self.status = "failed"
            self.error = type(error).__name__
            self.last_error = self.error


class ModuleKernel:
    """Petit registre d'état, indépendant des cogs et de Discord."""

    def __init__(
        self,
        modules: Iterable[str],
        critical: Iterable[str] = (),
        dependencies: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        module_names = tuple(modules)
        critical_set = set(critical)
        self._states = {
            name: ModuleState(name=name, critical=name in critical_set)
            for name in module_names
        }
        raw_dependencies = dependencies or {}
        self._dependencies = {
            name: tuple(dep for dep in raw_dependencies.get(name, ()) if dep in self._states)
            for name in module_names
        }
        self._events = deque(maxlen=120)

    def _event(self, name: str, event: str, **detail) -> None:
        self._events.append({
            "at": int(time.time()),
            "module": name,
            "event": event,
            **detail,
        })

    def begin(self, name: str, *, operation: str = "load") -> None:
        self._states[name].begin(operation=operation)
        self._event(name, "begin", operation=operation)

    def loaded(self, name: str) -> None:
        self._states[name].finish()
        self._event(name, "loaded")

    def failed(self, name: str, error: BaseException) -> None:
        self._states[name].finish(error=error)
        self._event(name, "failed", error=type(error).__name__)

    def blockers(self, name: str) -> tuple[str, ...]:
        return tuple(
            dep
            for dep in self._dependencies.get(name, ())
            if (
                self._states[dep].status != "loaded"
                or self._states[dep].circuit_open
            )
        )

    def dependents(self, name: str) -> tuple[str, ...]:
        return tuple(
            module
            for module, dependencies in self._dependencies.items()
            if name in dependencies
        )

    def blocked(self, name: str, dependencies: Iterable[str]) -> None:
        state = self._states[name]
        state.status = "blocked"
        state.error = None
        state.blocked_by = tuple(sorted(set(dependencies)))
        state.last_operation = "dependency-wait"
        state._started_at = None
        self._event(name, "blocked", blocked_by=list(state.blocked_by))

    def recovered(self, name: str, error: BaseException) -> None:
        """Une opération a échoué mais l'ancienne extension reste disponible."""
        state = self._states[name]
        if state._started_at is not None:
            state.load_ms = round((time.perf_counter() - state._started_at) * 1000, 2)
        state._started_at = None
        state.status = "loaded"
        state.error = None
        state.blocked_by = ()
        state.last_error = type(error).__name__
        self._event(name, "recovered", error=type(error).__name__)

    def unloaded(self, name: str) -> None:
        state = self._states[name]
        state.status = "unloaded"
        state.error = None
        state.blocked_by = ()
        state.load_ms = None
        state._started_at = None
        state.last_operation = "unload"
        self._event(name, "unloaded")

    def is_critical(self, name: str) -> bool:
        return self._states[name].critical

    def contains(self, name: str) -> bool:
        return name in self._states

    def enter_runtime(self, name: str) -> None:
        if name not in self._states:
            return
        state = self._states[name]
        if state.in_flight == 0:
            state.in_flight_since = time.time()
        state.in_flight += 1

    def exit_runtime(self, name: str) -> None:
        if name not in self._states:
            return
        state = self._states[name]
        state.in_flight = max(0, state.in_flight - 1)
        if state.in_flight == 0:
            state.in_flight_since = None

    def in_flight(self, name: str) -> int:
        if name not in self._states:
            return 0
        return int(self._states[name].in_flight)

    def record_runtime_error(
        self,
        name: str,
        error: BaseException | str,
        *,
        threshold: int = 3,
        circuit_threshold: int = 5,
        error_window_seconds: int = 300,
    ) -> None:
        if name not in self._states:
            return
        state = self._states[name]
        now = time.time()

        # Une erreur ancienne ne doit pas compter comme "consécutive" avec une
        # nouvelle erreur beaucoup plus tard. Le circuit protège les rafales de
        # panne, pas les incidents isolés répartis sur plusieurs heures.
        if (
            state.last_runtime_error_at is not None
            and now - state.last_runtime_error_at > max(1, int(error_window_seconds))
        ):
            state.consecutive_runtime_errors = 0
            state.runtime_degraded = False
            if not state.circuit_open:
                state.circuit_opened_at = None

        state.runtime_errors += 1
        state.consecutive_runtime_errors += 1
        state.last_runtime_error = error if isinstance(error, str) else type(error).__name__
        state.last_runtime_error_at = now
        state.runtime_degraded = state.consecutive_runtime_errors >= max(1, int(threshold))

        # Les modules critiques ne sont jamais ouverts automatiquement.
        if (
            not state.critical
            and state.status == "loaded"
            and state.consecutive_runtime_errors >= max(1, int(circuit_threshold))
        ):
            if not state.circuit_open:
                state.circuit_open = True
                state.circuit_opened_at = time.time()
                state.circuit_reason = "runtime_errors"
                self._event(
                    name,
                    "circuit_open",
                    reason="runtime_errors",
                    consecutive_errors=state.consecutive_runtime_errors,
                )

    def record_runtime_success(self, name: str) -> None:
        if name not in self._states:
            return
        state = self._states[name]

        # Un succès de commande ne doit jamais annuler un circuit structurel
        # (maintenance, boucle de fond morte, arrêt manuel). Seuls les circuits
        # ouverts par une rafale d'erreurs de commandes peuvent être refermés
        # par une exécution réussie.
        if state.circuit_open and state.circuit_reason not in {None, "runtime_errors"}:
            return

        state.consecutive_runtime_errors = 0
        state.runtime_degraded = False
        was_open = state.circuit_open
        state.circuit_open = False
        state.circuit_opened_at = None
        state.circuit_reason = None
        if was_open:
            self._event(name, "circuit_closed", reason="runtime_success")

    def open_circuit(
        self,
        name: str,
        *,
        reason: str = "manual",
        replace_reason: bool = False,
    ) -> None:
        if name not in self._states:
            return
        state = self._states[name]
        if state.critical:
            return
        if not state.circuit_open:
            state.circuit_open = True
            state.circuit_opened_at = time.time()
            state.circuit_reason = reason
            self._event(name, "circuit_open", reason=reason)
        elif replace_reason and state.circuit_reason != reason:
            state.circuit_reason = reason
            self._event(name, "circuit_reason", reason=reason)

    def close_circuit(self, name: str, *, reason: str = "reload") -> None:
        if name not in self._states:
            return
        state = self._states[name]
        was_open = state.circuit_open
        state.circuit_open = False
        state.circuit_opened_at = None
        state.circuit_reason = None
        state.consecutive_runtime_errors = 0
        state.runtime_degraded = False
        if was_open:
            self._event(name, "circuit_closed", reason=reason)

    def reconcile(self, loaded_modules: Iterable[str]) -> list[str]:
        """Aligne le registre sur la vérité runtime de discord.py.

        Un module marqué chargé mais absent du registre d'extensions devient failed.
        À l'inverse, un module présent dans discord.py mais encore marqué failed/blocked
        redevient loaded. Les modules volontairement unloaded ne sont jamais réactivés
        par cette simple observation.
        """
        actual = set(loaded_modules)
        changed: list[str] = []
        for name, state in self._states.items():
            if state.status == "loaded" and name not in actual:
                state.status = "failed"
                state.error = "RuntimeMissing"
                state.last_error = "RuntimeMissing"
                state.last_operation = "runtime-reconcile"
                state.blocked_by = ()
                changed.append(name)
            elif state.status in {"failed", "blocked"} and name in actual:
                state.status = "loaded"
                state.error = None
                state.blocked_by = ()
                state.last_operation = "runtime-reconcile"
                changed.append(name)
        return changed

    def validate_invariants(self) -> list[str]:
        problems: list[str] = []
        valid_statuses = {"pending", "loading", "loaded", "failed", "blocked", "unloaded"}

        for name, state in self._states.items():
            if state.status not in valid_statuses:
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

    def snapshot(self) -> dict:
        rows = list(self._states.values())
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
        loaded = sum(row.status == "loaded" for row in rows)
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
        invariant_errors = self.validate_invariants()
        return {
            "expected": len(rows),
            "loaded": loaded,
            "failed": failed,
            "blocked": blocked,
            "critical_failed": critical_failed,
            "critical_runtime_degraded": critical_runtime_degraded,
            "ready": not critical_failed and not critical_runtime_degraded and not invariant_errors,
            "invariant_errors": invariant_errors,
            "runtime_degraded": runtime_degraded,
            "open_circuits": open_circuits,
            "recent_events": list(self._events)[-20:],
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
