"""P4 deployment engine with resume, rollback and fencing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from services.orchestrator.store import Deployment, DeploymentStatus, MemoryWorkflowStore

_STEPS = ("test", "prewarm", "handover", "health")


@dataclass
class DeploymentHooks:
    test: Callable[[Deployment], None]
    prewarm: Callable[[Deployment], None]
    handover: Callable[[Deployment], None]
    health: Callable[[Deployment], bool]
    rollback: Callable[[Deployment], None]


class DeploymentEngine:
    def __init__(self, store: MemoryWorkflowStore, hooks: DeploymentHooks) -> None:
        self.store = store
        self.hooks = hooks

    def run(
        self,
        deployment_id: str,
        *,
        worker: str,
        now: float,
        max_steps: int | None = None,
    ) -> Deployment:
        dep = self.store.deployments[deployment_id]
        lease = self.store.acquire(deployment_id, worker, now)
        if lease is None:
            return dep
        dep.status = DeploymentStatus.RUNNING
        executed = 0
        while dep.step_index < len(_STEPS):
            if max_steps is not None and executed >= max_steps:
                break
            step = _STEPS[dep.step_index]
            try:
                if step == "test":
                    self.store.once(dep.id, lease.fencing_token, "test", lambda: self.hooks.test(dep))
                elif step == "prewarm":
                    self.store.once(dep.id, lease.fencing_token, "prewarm", lambda: self.hooks.prewarm(dep))
                elif step == "handover":
                    def do_handover() -> None:
                        self.hooks.handover(dep)
                        dep.active_release_id = dep.release_id
                    self.store.once(dep.id, lease.fencing_token, "handover", do_handover)
                elif step == "health":
                    healthy = self.hooks.health(dep)
                    if not healthy:
                        def do_rollback() -> None:
                            self.hooks.rollback(dep)
                            dep.active_release_id = dep.previous_release_id
                        self.store.once(dep.id, lease.fencing_token, "rollback", do_rollback)
                        dep.status = DeploymentStatus.ROLLED_BACK
                        dep.error = "health window failed"
                        dep.step_index += 1
                        return dep
                dep.step_index += 1
                executed += 1
                self.store.attempts.append((dep.id, worker, lease.fencing_token, step))
            except Exception as exc:
                # A failure before handover leaves the previous release active.
                if dep.active_release_id == dep.release_id and dep.previous_release_id is not None:
                    def do_rollback_error() -> None:
                        self.hooks.rollback(dep)
                        dep.active_release_id = dep.previous_release_id
                    self.store.once(dep.id, lease.fencing_token, "rollback", do_rollback_error)
                    dep.status = DeploymentStatus.ROLLED_BACK
                else:
                    dep.status = DeploymentStatus.FAILED
                dep.error = str(exc)
                return dep
        if dep.step_index == len(_STEPS) and dep.status == DeploymentStatus.RUNNING:
            dep.status = DeploymentStatus.SUCCEEDED
        return dep
