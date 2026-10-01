"""Journal technique borné du micro-kernel SentriX."""
from __future__ import annotations

import time
from collections import deque


class ModuleJournal:
    def __init__(self, *, capacity: int = 120) -> None:
        self._events = deque(maxlen=max(20, int(capacity)))

    def add(self, module: str, event: str, **detail) -> None:
        self._events.append({
            "at": int(time.time()),
            "module": module,
            "event": event,
            **detail,
        })

    def recent(self, limit: int = 20) -> list[dict]:
        return list(self._events)[-max(1, int(limit)):]
