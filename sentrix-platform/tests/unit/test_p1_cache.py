from pathlib import Path
from uuid import uuid4

from agents.node_agent.cache import DesiredCache
from libs.runtime_models import AgentDesiredInstance


def test_cache_round_trip(tmp_path: Path) -> None:
    item = AgentDesiredInstance(
        instance_id=uuid4(),
        desired_state="running",
        image_ref="python:3.12-alpine",
        command=["python", "-c", "pass"],
        cpu_millis=250,
        memory_mb=128,
        pids_limit=64,
        generation=3,
    )
    cache = DesiredCache(tmp_path / "desired.json")
    cache.save([item])
    loaded = cache.load()
    assert loaded == [item]
    assert (tmp_path / "desired.json").stat().st_mode & 0o777 == 0o600
