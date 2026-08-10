from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OrgLogQuota:
    bytes_per_window: int = 1_000_000
    window_seconds: float = 60.0
    usage: dict[str, tuple[float, int]] = field(default_factory=dict)

    def allow(self, org_id: str, size: int, now: float) -> bool:
        if size < 0:
            raise ValueError("negative log size")
        start, used = self.usage.get(org_id, (now, 0))
        if now - start >= self.window_seconds:
            start, used = now, 0
        if used + size > self.bytes_per_window:
            self.usage[org_id] = (start, used)
            return False
        self.usage[org_id] = (start, used + size)
        return True
