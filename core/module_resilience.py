"""Résilience runtime d'un module SentriX.

Gère uniquement appels en vol, dégradation et circuit breaker. Le registre principal
reste responsable de la liste des modules et des dépendances.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Mapping

from core.module_state import ModuleState


class ModuleResilience:
    def __init__(
        self,
        states: Mapping[str, ModuleState],
        event: Callable[..., None],
    ) -> None:
        self._states = states
        self._event = event

    def enter(self, name: str) -> None:
        state = self._states.get(name)
        if state is None:
            return
        if state.in_flight == 0:
            state.in_flight_since = time.time()
        state.in_flight += 1

    def exit(self, name: str) -> None:
        state = self._states.get(name)
        if state is None:
            return
        state.in_flight = max(0, state.in_flight - 1)
        if state.in_flight == 0:
            state.in_flight_since = None

    def in_flight(self, name: str) -> int:
        state = self._states.get(name)
        return int(state.in_flight) if state is not None else 0

    def record_error(
        self,
        name: str,
        error: BaseException | str,
        *,
        threshold: int = 3,
        circuit_threshold: int = 5,
        error_window_seconds: int = 300,
    ) -> None:
        state = self._states.get(name)
        if state is None:
            return

        now = time.time()
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
        state.runtime_degraded = (
            state.consecutive_runtime_errors >= max(1, int(threshold))
        )

        if (
            not state.critical
            and state.status == "loaded"
            and state.consecutive_runtime_errors >= max(1, int(circuit_threshold))
            and not state.circuit_open
        ):
            state.circuit_open = True
            state.circuit_opened_at = now
            state.circuit_reason = "runtime_errors"
            self._event(
                name,
                "circuit_open",
                reason="runtime_errors",
                consecutive_errors=state.consecutive_runtime_errors,
            )

    def decay(self, *, quiet_window_seconds: int = 300) -> list[str]:
        """Rétablit les modules dégradés après une vraie période calme."""
        now = time.time()
        recovered: list[str] = []
        window = max(1, int(quiet_window_seconds))
        for name, state in self._states.items():
            if not state.runtime_degraded:
                continue
            if state.circuit_open:
                continue
            if state.last_runtime_error_at is None:
                continue
            if now - state.last_runtime_error_at < window:
                continue
            state.consecutive_runtime_errors = 0
            state.runtime_degraded = False
            recovered.append(name)
            self._event(name, "runtime_decay_recovered")
        return recovered

    def record_success(self, name: str) -> None:
        state = self._states.get(name)
        if state is None:
            return
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
        state = self._states.get(name)
        if state is None or state.critical:
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
        state = self._states.get(name)
        if state is None:
            return

        was_open = state.circuit_open
        state.circuit_open = False
        state.circuit_opened_at = None
        state.circuit_reason = None
        state.consecutive_runtime_errors = 0
        state.runtime_degraded = False
        if was_open:
            self._event(name, "circuit_closed", reason=reason)
