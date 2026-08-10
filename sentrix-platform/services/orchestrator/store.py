"""Durable-workflow semantics for P4.

The production adapter maps these operations to PostgreSQL leases and attempts.
This in-memory reference implementation is deliberately strict and is used by
contract tests to prove fencing/idempotence semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DeploymentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class StaleFencingToken(RuntimeError):  # noqa: N818 - public domain exception name
    pass


@dataclass(slots=True)
class Lease:
    owner: str
    expires_at: float
    fencing_token: int


@dataclass(slots=True)
class Deployment:
    id: str
    environment_id: str
    release_id: str
    previous_release_id: str | None
    runtime_mode: str = "managed"
    status: DeploymentStatus = DeploymentStatus.PENDING
    step_index: int = 0
    active_release_id: str | None = None
    error: str | None = None


@dataclass
class MemoryWorkflowStore:
    deployments: dict[str, Deployment] = field(default_factory=dict)
    leases: dict[str, Lease] = field(default_factory=dict)
    fence_counters: dict[str, int] = field(default_factory=dict)
    effects: set[tuple[str, str]] = field(default_factory=set)
    attempts: list[tuple[str, str, int, str]] = field(default_factory=list)

    def acquire(
        self, deployment_id: str, worker: str, now: float, ttl: float = 15.0
    ) -> Lease | None:
        current = self.leases.get(deployment_id)
        if current and current.expires_at > now and current.owner != worker:
            return None
        if current and current.expires_at > now and current.owner == worker:
            current.expires_at = now + ttl
            return current
        token = self.fence_counters.get(deployment_id, 0) + 1
        self.fence_counters[deployment_id] = token
        lease = Lease(worker, now + ttl, token)
        self.leases[deployment_id] = lease
        return lease

    def renew(
        self, deployment_id: str, worker: str, token: int, now: float, ttl: float = 15.0
    ) -> None:
        self.assert_fence(deployment_id, token, worker)
        self.leases[deployment_id].expires_at = now + ttl

    def assert_fence(self, deployment_id: str, token: int, worker: str | None = None) -> None:
        current = self.leases.get(deployment_id)
        if (
            current is None
            or current.fencing_token != token
            or (worker is not None and current.owner != worker)
        ):
            raise StaleFencingToken("stale deployment fencing token")

    def once(self, deployment_id: str, token: int, key: str, fn: object) -> bool:
        self.assert_fence(deployment_id, token)
        marker = (deployment_id, key)
        if marker in self.effects:
            return False
        if not callable(fn):
            raise TypeError("side effect must be callable")
        fn()
        self.effects.add(marker)
        return True
