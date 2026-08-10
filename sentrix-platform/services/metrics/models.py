from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeMetrics:
    instance_id: str
    cpu_ratio: float
    memory_bytes: int
    gateway_latency_ms: float | None

    def prometheus_labels(self) -> dict[str, str]:
        # No org/user controlled strings beyond opaque instance_id in labels.
        return {"instance_id": self.instance_id}
