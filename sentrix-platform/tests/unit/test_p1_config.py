import pytest

from agents.node_agent.config import AgentConfig


def test_runtime_must_be_runsc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTRIX_CONTROL_PLANE_URL", "https://cp.example")
    monkeypatch.setenv("SENTRIX_NODE_ID", "00000000-0000-0000-0000-000000000001")
    monkeypatch.setenv("SENTRIX_NODE_TOKEN", "x" * 32)
    monkeypatch.setenv("SENTRIX_SANDBOX_RUNTIME", "runc")
    with pytest.raises(RuntimeError, match="runsc"):
        AgentConfig.from_env()
