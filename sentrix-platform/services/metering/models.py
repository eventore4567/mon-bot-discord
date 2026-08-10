from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UsageSample:
    org_id: str
    environment_id: str
    ts_ms: int
    cpu_millis: int
    memory_bytes: int
    egress_bytes: int
    log_bytes: int

    def validate(self) -> None:
        if (
            min(self.ts_ms, self.cpu_millis, self.memory_bytes, self.egress_bytes, self.log_bytes)
            < 0
        ):
            raise ValueError("usage samples cannot contain negative counters")
