from __future__ import annotations

import pytest

from libs.managed_runtime import GatewayIdentifyGate
from services.identify_broker.broker import BucketCoolingDown, BudgetUnavailable, IdentifyBroker
from services.identify_broker.breaker import CircuitBreaker
from services.identify_broker.model import IdentifyBudget, ReservationState
from services.identify_broker.store import MemoryIdentifyStore


def broker_for(*, remaining: int = 20, max_concurrency: int = 1, failures: int = 5) -> IdentifyBroker:
    store = MemoryIdentifyStore()
    store.budgets["app"] = IdentifyBudget("app", 1000, remaining, 60_000, max_concurrency, rollback_reserve=2, floor=3)
    broker = IdentifyBroker(store)
    broker.breakers["app"] = CircuitBreaker(max_failures=failures, base_backoff_seconds=1)
    return broker


def test_identify_sent_is_persisted_before_opcode2_callback() -> None:
    broker = broker_for()
    gate = GatewayIdentifyGate(broker)
    observed: list[ReservationState] = []

    def send() -> None:
        reservation = next(iter(broker.store.reservations.values()))
        observed.append(reservation.state)

    gate.identify("app", 0, send, now=10.0)
    assert observed == [ReservationState.IDENTIFY_SENT]
    assert broker.store.budgets["app"].remaining_local == 19


def test_release_is_impossible_after_identify() -> None:
    broker = broker_for()
    r = broker.reserve("app", 0, now=0)
    broker.persist_identify_sent(r.id, now=0)
    with pytest.raises(ValueError):
        broker.release_before_identify(r.id, now=1)


def test_failed_after_identify_remains_consumed_and_reconcile_is_conservative() -> None:
    broker = broker_for(remaining=20)
    r = broker.reserve("app", 0, now=0)
    broker.persist_identify_sent(r.id, now=0)
    broker.failed_after_identify(r.id, now=1)
    assert r.state == ReservationState.FAILED_AFTER_IDENTIFY
    assert r.consumed
    assert broker.reconcile_discord("app", 12) == 12
    assert broker.reconcile_discord("app", 18) == 12  # never increases from refresh


def test_budget_is_per_discord_application() -> None:
    store = MemoryIdentifyStore()
    store.budgets["prod"] = IdentifyBudget("prod", 1000, 100, 1, 1, floor=1, rollback_reserve=0)
    store.budgets["canary"] = IdentifyBudget("canary", 1000, 50, 1, 1, floor=1, rollback_reserve=0)
    b = IdentifyBroker(store)
    r = b.reserve("prod", 0, now=0)
    b.persist_identify_sent(r.id, now=0)
    assert store.budgets["prod"].remaining_local == 99
    assert store.budgets["canary"].remaining_local == 50


def test_bucket_serialization_has_five_second_window() -> None:
    broker = broker_for(max_concurrency=1)
    a = broker.reserve("app", 0, now=0)
    broker.persist_identify_sent(a.id, now=0)
    b = broker.reserve("app", 1, now=1)
    with pytest.raises(BucketCoolingDown):
        broker.persist_identify_sent(b.id, now=4.999)
    broker.persist_identify_sent(b.id, now=5.0)


def test_crash_loop_is_bounded_and_requires_human_reset() -> None:
    broker = broker_for(remaining=20, failures=5)
    sent = 0
    for i in range(5):
        r = broker.reserve("app", 0, now=i * 5.0)
        broker.persist_identify_sent(r.id, now=i * 5.0)
        sent += 1
        broker.failed_after_identify(r.id, now=i * 5.0 + 0.1)
    assert sent == 5
    assert broker.store.budgets["app"].remaining_local == 15
    assert broker.breaker("app").tripped
    with pytest.raises(BudgetUnavailable):
        broker.reserve("app", 0, now=30)
    broker.breaker("app").human_reset()
    assert broker.reserve("app", 0, now=30).state == ReservationState.HELD


def test_crash_between_persist_and_send_only_overestimates() -> None:
    broker = broker_for(remaining=20)
    r = broker.reserve("app", 0, now=0)
    broker.persist_identify_sent(r.id, now=0)
    actual_opcodes_sent = 0  # process dies here, before send
    local_consumed = 20 - broker.store.budgets["app"].remaining_local
    assert actual_opcodes_sent == 0
    assert local_consumed == 1  # safe bias: overestimate, never underestimate
