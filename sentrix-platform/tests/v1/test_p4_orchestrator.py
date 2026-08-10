from __future__ import annotations

import pytest

from services.orchestrator.command_sync import needs_sync
from services.orchestrator.engine import DeploymentEngine, DeploymentHooks
from services.orchestrator.store import Deployment, DeploymentStatus, MemoryWorkflowStore, StaleFencingToken
from services.scheduler.planner import plan_for


class Hooks:
    def __init__(self, healthy: bool = True) -> None:
        self.events: list[str] = []
        self.healthy = healthy

    def bundle(self) -> DeploymentHooks:
        return DeploymentHooks(
            test=lambda _d: self.events.append("test"),
            prewarm=lambda _d: self.events.append("prewarm"),
            handover=lambda _d: self.events.append("handover"),
            health=lambda _d: self.events.append("health") or self.healthy,
            rollback=lambda _d: self.events.append("rollback"),
        )


def dep(identifier: str = "d1") -> Deployment:
    return Deployment(identifier, "env", "release-new", "release-old", active_release_id="release-old")


def test_broken_release_auto_rolls_back_without_intervention() -> None:
    store = MemoryWorkflowStore(deployments={"d1": dep()})
    hooks = Hooks(healthy=False)
    result = DeploymentEngine(store, hooks.bundle()).run("d1", worker="w1", now=0)
    assert result.status == DeploymentStatus.ROLLED_BACK
    assert result.active_release_id == "release-old"
    assert hooks.events == ["test", "prewarm", "handover", "health", "rollback"]


def test_orchestrator_death_is_resumed_without_duplicate_effects() -> None:
    store = MemoryWorkflowStore(deployments={"d1": dep()})
    hooks = Hooks(healthy=True)
    engine = DeploymentEngine(store, hooks.bundle())
    half = engine.run("d1", worker="w1", now=0, max_steps=2)
    assert half.step_index == 2
    # Worker w1 disappears. After lease expiry, w2 continues from durable step.
    done = engine.run("d1", worker="w2", now=20)
    assert done.status == DeploymentStatus.SUCCEEDED
    assert hooks.events == ["test", "prewarm", "handover", "health"]
    attempted_steps = [x[3] for x in store.attempts]
    assert attempted_steps == ["test", "prewarm", "handover", "health"]


def test_zombie_worker_is_fenced_after_lease_expiry() -> None:
    store = MemoryWorkflowStore(deployments={"d1": dep()})
    old = store.acquire("d1", "old", 0, ttl=5)
    assert old is not None
    new = store.acquire("d1", "new", 10, ttl=5)
    assert new is not None and new.fencing_token > old.fencing_token
    with pytest.raises(StaleFencingToken):
        store.once("d1", old.fencing_token, "zombie-call", lambda: None)


def test_same_release_can_have_distinct_deployments() -> None:
    store = MemoryWorkflowStore()
    store.deployments["d1"] = Deployment("d1", "env", "same-release", None)
    store.deployments["d2"] = Deployment("d2", "env", "same-release", None)
    assert store.deployments["d1"].release_id == store.deployments["d2"].release_id
    assert store.deployments["d1"].id != store.deployments["d2"].id


def test_runtime_plans_make_health_difference_explicit() -> None:
    managed = plan_for("managed")
    generic = plan_for("generic")
    assert managed.prewarm == "process-warm-gateway-held"
    assert managed.health_level == "gateway-rich"
    assert generic.prewarm == "image-network-only"
    assert generic.health_level == "process-liveness"


def test_slash_commands_sync_only_when_hash_changes() -> None:
    commands = [{"name": "ping", "description": "pong"}]
    changed, current = needs_sync(None, commands)
    assert changed
    changed, same = needs_sync(current, commands)
    assert not changed and same == current
