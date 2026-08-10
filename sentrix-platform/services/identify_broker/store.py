from __future__ import annotations

from dataclasses import dataclass, field
from services.identify_broker.model import IdentifyBudget, Reservation


@dataclass
class MemoryIdentifyStore:
    budgets: dict[str, IdentifyBudget] = field(default_factory=dict)
    reservations: dict[str, Reservation] = field(default_factory=dict)
    bucket_last_sent: dict[tuple[str, int], float] = field(default_factory=dict)

    def budget(self, application_id: str) -> IdentifyBudget:
        try:
            return self.budgets[application_id]
        except KeyError as exc:
            raise KeyError(f"budget missing for application {application_id}") from exc
