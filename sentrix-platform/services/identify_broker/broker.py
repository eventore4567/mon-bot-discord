"""P3 IdentifyBroker core.

Critical invariant: ``identify_sent`` is persisted and budget is consumed BEFORE
an opcode 2 may be sent. A crash in between safely over-counts by one.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from services.identify_broker.breaker import CircuitBreaker
from services.identify_broker.model import Reservation, ReservationState
from services.identify_broker.store import MemoryIdentifyStore


class BudgetUnavailable(RuntimeError):
    pass


class BucketCoolingDown(RuntimeError):
    pass


@dataclass
class IdentifyBroker:
    store: MemoryIdentifyStore
    bucket_window_seconds: float = 5.0
    breakers: dict[str, CircuitBreaker] = field(default_factory=dict)

    def breaker(self, application_id: str) -> CircuitBreaker:
        return self.breakers.setdefault(application_id, CircuitBreaker())

    def reserve(
        self,
        application_id: str,
        shard_id: int,
        *,
        urgent_rollback: bool = False,
        now: float | None = None,
    ) -> Reservation:
        if not self.breaker(application_id).allow():
            raise BudgetUnavailable("identify breaker is tripped")
        budget = self.store.budget(application_id)
        if not budget.can_reserve(urgent_rollback=urgent_rollback):
            raise BudgetUnavailable("identify budget floor/reserve reached")
        r = Reservation(
            id=str(uuid.uuid4()),
            application_id=application_id,
            shard_id=shard_id,
            max_concurrency=budget.max_concurrency,
            created_at=time.monotonic() if now is None else now,
            updated_at=time.monotonic() if now is None else now,
        )
        self.store.reservations[r.id] = r
        return r

    def persist_identify_sent(self, reservation_id: str, *, now: float | None = None) -> None:
        """Persist consumption before the caller sends opcode 2."""
        r = self.store.reservations[reservation_id]
        stamp = time.monotonic() if now is None else now
        key = (r.application_id, r.bucket)
        previous = self.store.bucket_last_sent.get(key)
        if previous is not None and stamp - previous < self.bucket_window_seconds:
            raise BucketCoolingDown("identify bucket is inside the 5s window")
        # The state write occurs conceptually before the outbound side effect.
        r.transition(ReservationState.IDENTIFY_SENT, now=stamp)
        self.store.budget(r.application_id).consume()
        self.store.bucket_last_sent[key] = stamp

    def ready(self, reservation_id: str, *, now: float | None = None) -> None:
        self.store.reservations[reservation_id].transition(ReservationState.READY, now=now)

    def failed_after_identify(self, reservation_id: str, *, now: float | None = None) -> float:
        r = self.store.reservations[reservation_id]
        r.transition(ReservationState.FAILED_AFTER_IDENTIFY, now=now)
        stamp = time.monotonic() if now is None else now
        return self.breaker(r.application_id).record_failure(stamp)

    def release_before_identify(self, reservation_id: str, *, now: float | None = None) -> None:
        self.store.reservations[reservation_id].transition(ReservationState.RELEASED, now=now)

    def reconcile_discord(self, application_id: str, discord_remaining: int) -> int:
        budget = self.store.budget(application_id)
        budget.reconcile(discord_remaining)
        return budget.remaining_local
