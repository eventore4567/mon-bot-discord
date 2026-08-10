"""Identify reservation state and budget models (P3)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum


class ReservationState(StrEnum):
    HELD = "held"
    IDENTIFY_SENT = "identify_sent"
    READY = "ready"
    RELEASED = "released"
    FAILED_AFTER_IDENTIFY = "failed_after_identify"


CONSUMED_STATES = {
    ReservationState.IDENTIFY_SENT,
    ReservationState.READY,
    ReservationState.FAILED_AFTER_IDENTIFY,
}


@dataclass(slots=True)
class Reservation:
    id: str
    application_id: str
    shard_id: int
    max_concurrency: int
    state: ReservationState = ReservationState.HELD
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def bucket(self) -> int:
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        return self.shard_id % self.max_concurrency

    @property
    def consumed(self) -> bool:
        return self.state in CONSUMED_STATES

    def transition(self, new_state: ReservationState, *, now: float | None = None) -> None:
        allowed = {
            ReservationState.HELD: {ReservationState.IDENTIFY_SENT, ReservationState.RELEASED},
            ReservationState.IDENTIFY_SENT: {
                ReservationState.READY,
                ReservationState.FAILED_AFTER_IDENTIFY,
            },
            ReservationState.READY: set(),
            ReservationState.RELEASED: set(),
            ReservationState.FAILED_AFTER_IDENTIFY: set(),
        }
        if new_state not in allowed[self.state]:
            raise ValueError(f"illegal reservation transition {self.state} -> {new_state}")
        self.state = new_state
        self.updated_at = time.monotonic() if now is None else now


@dataclass(slots=True)
class IdentifyBudget:
    application_id: str
    total: int
    remaining_local: int
    reset_after_ms: int
    max_concurrency: int
    rollback_reserve: int = 2
    floor: int = 5

    def reconcile(self, discord_remaining: int) -> None:
        if discord_remaining < 0:
            raise ValueError("discord remaining cannot be negative")
        # Discord is authoritative and the local estimator is deliberately
        # conservative. Never increase remaining from an API refresh.
        self.remaining_local = min(self.remaining_local, discord_remaining)

    def can_reserve(self, *, urgent_rollback: bool = False) -> bool:
        required = 1 if urgent_rollback else max(self.floor, self.rollback_reserve + 1)
        return self.remaining_local >= required

    def consume(self) -> None:
        if self.remaining_local <= 0:
            raise RuntimeError("identify budget exhausted")
        self.remaining_local -= 1
