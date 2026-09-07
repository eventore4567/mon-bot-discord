import pytest

from agents.node_agent.config import AgentConfig


def _valid_env(monkeypatch: pytest.MonkeyPatch, control_plane_url: str) -> None:
    monkeypatch.setenv("SENTRIX_CONTROL_PLANE_URL", control_plane_url)
    monkeypatch.setenv("SENTRIX_NODE_ID", "00000000-0000-0000-0000-000000000001")
    monkeypatch.setenv("SENTRIX_NODE_TOKEN", "x" * 32)
    monkeypatch.setenv("SENTRIX_SANDBOX_RUNTIME", "runsc")


def test_runtime_must_be_runsc(monkeypatch: pytest.MonkeyPatch) -> None:
    _valid_env(monkeypatch, "https://cp.example")
    monkeypatch.setenv("SENTRIX_SANDBOX_RUNTIME", "runc")
    with pytest.raises(RuntimeError, match="runsc"):
        AgentConfig.from_env()


def test_remote_control_plane_requires_https(monkeypatch: pytest.MonkeyPatch) -> None:
    _valid_env(monkeypatch, "http://cp.example")
    with pytest.raises(RuntimeError, match="HTTPS hors localhost"):
        AgentConfig.from_env()


def test_local_http_control_plane_is_allowed_for_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    _valid_env(monkeypatch, "http://127.0.0.1:8000")
    assert AgentConfig.from_env().control_plane_url == "http://127.0.0.1:8000"


def test_control_plane_url_must_be_absolute(monkeypatch: pytest.MonkeyPatch) -> None:
    _valid_env(monkeypatch, "cp.example")
    with pytest.raises(RuntimeError, match=r"URL http\(s\) absolue"):
        AgentConfig.from_env()
