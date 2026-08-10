import json
from pathlib import Path
from uuid import uuid4

import pytest

from agents.node_agent.docker_runtime import DockerRuntime
from libs.runtime_models import AgentDesiredInstance


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.inspect_id: str | None = None

    async def run(self, *args: str, check: bool = True) -> str:
        del check
        self.calls.append(args)
        if len(args) >= 3 and args[1:3] == ("ps", "-aq"):
            return self.inspect_id or ""
        if len(args) >= 3 and args[1:3] == ("network", "ls"):
            return "network-id"
        if len(args) >= 2 and args[1] == "run":
            self.inspect_id = "cid-new"
            return "cid-new"
        if len(args) >= 2 and args[1] == "inspect":
            return json.dumps(
                [
                    {
                        "State": {"Running": True, "ExitCode": 0},
                        "Config": {"Labels": {"sentrix.generation": "4"}},
                    }
                ]
            )
        return ""


@pytest.mark.asyncio
async def test_run_is_hardened_and_quota_bound() -> None:
    runner = FakeRunner()
    runtime = DockerRuntime("docker", "runsc", Path("/bin/true"), (), runner=runner)  # type: ignore[arg-type]
    spec = AgentDesiredInstance(
        instance_id=uuid4(),
        desired_state="running",
        image_ref="python:3.12-alpine",
        command=["sleep", "3600"],
        cpu_millis=250,
        memory_mb=128,
        pids_limit=64,
        generation=4,
    )
    await runtime.start(spec)
    run = next(call for call in runner.calls if len(call) > 1 and call[1] == "run")
    joined = " ".join(run)
    assert "--runtime runsc" in joined
    assert "--read-only" in run
    assert "--cap-drop ALL" in joined
    assert "no-new-privileges:true" in run
    assert "--cpus 0.250" in joined
    assert "--memory 128m" in joined
    assert "--memory-swap 128m" in joined
    assert "--pids-limit 64" in joined
    assert "/var/run/docker.sock" not in joined
    assert "--privileged" not in run
