from pathlib import Path
from uuid import uuid4

import pytest

from agents.node_agent.cache import DesiredCache
from agents.node_agent.docker_runtime import ContainerObservation
from agents.node_agent.reconciler import Reconciler
from libs.runtime_models import AgentDesiredInstance, AgentObservedInstance


class FakeClient:
    def __init__(self, desired: list[AgentDesiredInstance]) -> None:
        self.desired = desired
        self.fail = False
        self.reports: list[list[AgentObservedInstance]] = []

    async def pull(self) -> list[AgentDesiredInstance]:
        if self.fail:
            raise OSError("cp down")
        return self.desired

    async def report(self, statuses: list[AgentObservedInstance]) -> None:
        self.reports.append(statuses)


class FakeRuntime:
    def __init__(self) -> None:
        self.started: list[AgentDesiredInstance] = []

    async def start(self, spec: AgentDesiredInstance) -> ContainerObservation:
        self.started.append(spec)
        return ContainerObservation(spec.instance_id, "cid", "running", spec.generation, 0)

    async def stop(self, instance_id):  # type: ignore[no-untyped-def]
        return ContainerObservation(instance_id, None, "stopped", 0, 0)

    async def list_managed_instance_ids(self):  # type: ignore[no-untyped-def]
        return set()

    @staticmethod
    def to_report(obs: ContainerObservation, *, detail: str | None = None) -> AgentObservedInstance:
        return AgentObservedInstance(
            instance_id=obs.instance_id,
            observed_state="running" if obs.state == "running" else "stopped",
            container_id=obs.container_id,
            generation=obs.generation,
            health="healthy" if obs.state == "running" else "unknown",
            detail=detail,
        )


@pytest.mark.asyncio
async def test_control_plane_outage_reuses_cache(tmp_path: Path) -> None:
    spec = AgentDesiredInstance(
        instance_id=uuid4(),
        desired_state="running",
        image_ref="img",
        command=[],
        cpu_millis=100,
        memory_mb=64,
        pids_limit=32,
        generation=1,
    )
    client = FakeClient([spec])
    runtime = FakeRuntime()
    reconciler = Reconciler(
        client, runtime, DesiredCache(tmp_path / "cache.json"), poll_seconds=0.01
    )  # type: ignore[arg-type]

    fresh, _ = await reconciler.reconcile_once()
    assert fresh is True
    client.fail = True
    fresh, _ = await reconciler.reconcile_once()
    assert fresh is False
    assert [item.instance_id for item in runtime.started] == [spec.instance_id, spec.instance_id]
