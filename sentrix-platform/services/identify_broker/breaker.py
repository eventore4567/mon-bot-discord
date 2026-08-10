"""Crash-loop circuit breaker for Gateway IDENTIFY protection."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class CircuitBreaker:
    max_failures: int = 5
    base_backoff_seconds: float = 2.0
    window_seconds: float = 60.0
    failures: list[float] = field(default_factory=list)
    tripped: bool = False

    def record_failure(self, now: float) -> float:
        if self.tripped:
            raise RuntimeError("breaker requires human reset")
        cutoff = now - self.window_seconds
        self.failures = [x for x in self.failures if x >= cutoff]
        self.failures.append(now)
        count = len(self.failures)
        if count >= self.max_failures:
            self.tripped = True
        # first failure has no enforced delay; exponential starts with second.
        if count < 2:
            return 0.0
        return self.base_backoff_seconds * math.pow(2, count - 2)

    def allow(self) -> bool:
        return not self.tripped

    def human_reset(self) -> None:
        self.failures.clear()
        self.tripped = False
