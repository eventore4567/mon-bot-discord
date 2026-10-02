"""Micro-kernel SentriX : registre minimal de santé des modules.

Le noyau ne connaît aucune logique métier Discord. Il suit uniquement l'état de
chargement des extensions afin qu'un module optionnel en panne reste isolé et
observable sans rendre tout le bot indisponible.
"""
from __future__ import annotations

import time
from typing import Iterable, Mapping

from core.module_journal import ModuleJournal
from core.module_resilience import ModuleResilience
from core.module_snapshot import build_snapshot, validate_invariants
from core.module_state import ModuleState


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
        self._journal = ModuleJournal(capacity=120)
        self._resilience = ModuleResilience(self._states, self._event)

    def _event(self, name: str, event: str, **detail) -> None:
        self._journal.add(name, event, **detail)

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
        self._resilience.enter(name)

    def exit_runtime(self, name: str) -> None:
        self._resilience.exit(name)

    def in_flight(self, name: str) -> int:
        return self._resilience.in_flight(name)

    def record_runtime_error(
        self,
        name: str,
        error: BaseException | str,
        *,
        threshold: int = 3,
        circuit_threshold: int = 5,
        error_window_seconds: int = 300,
    ) -> None:
        self._resilience.record_error(
            name,
            error,
            threshold=threshold,
            circuit_threshold=circuit_threshold,
            error_window_seconds=error_window_seconds,
        )

    def record_runtime_success(self, name: str) -> None:
        self._resilience.record_success(name)

    def decay_runtime_health(self, *, quiet_window_seconds: int = 300) -> list[str]:
        return self._resilience.decay(
            quiet_window_seconds=quiet_window_seconds,
        )

    def open_circuit(
        self,
        name: str,
        *,
        reason: str = "manual",
        replace_reason: bool = False,
    ) -> None:
        self._resilience.open_circuit(
            name,
            reason=reason,
            replace_reason=replace_reason,
        )

    def close_circuit(self, name: str, *, reason: str = "reload") -> None:
        self._resilience.close_circuit(name, reason=reason)


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
        return validate_invariants(self._states)

    def snapshot(self) -> dict:
        return build_snapshot(
            self._states,
            recent_events=self._journal.recent(20),
        )

