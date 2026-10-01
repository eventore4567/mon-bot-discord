"""État minimal d'une extension SentriX."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


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
