from __future__ import annotations

import pytest

from services.orchestrator.main import OrchestratorConfig


def _orchestrator_env(monkeypatch: pytest.MonkeyPatch, api_url: str) -> None:
    monkeypatch.setenv("SENTRIX_API_URL", api_url)
    monkeypatch.setenv("SENTRIX_CONTROL_WORKER_ID", "01920000-0000-7000-8000-000000000222")
    monkeypatch.setenv("SENTRIX_CONTROL_WORKER_TOKEN", "o" * 48)


def test_orchestrator_remote_http_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _orchestrator_env(monkeypatch, "http://control.example")
    with pytest.raises(RuntimeError, match="HTTPS outside localhost"):
        OrchestratorConfig.from_env()


def test_orchestrator_local_http_is_allowed_for_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    _orchestrator_env(monkeypatch, "http://127.0.0.1:8000")
    assert OrchestratorConfig.from_env().api_url == "http://127.0.0.1:8000"


def test_orchestrator_accepts_remote_https(monkeypatch: pytest.MonkeyPatch) -> None:
    _orchestrator_env(monkeypatch, "https://control.example")
    assert OrchestratorConfig.from_env().api_url == "https://control.example"
