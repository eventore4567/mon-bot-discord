from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from services.builder_ctl import network
from services.builder_ctl.models import BuildSandboxSpec
from services.builder_ctl.worker import WorkerConfig

ROOT = Path(__file__).resolve().parents[2]
WORKER_SOURCE = ROOT / "services" / "builder_ctl" / "worker.py"


def test_build_sandbox_rejects_default_docker_bridge() -> None:
    spec = BuildSandboxSpec(
        image="python:3.12-slim",
        command=("python", "-V"),
        network_name="bridge",
    )
    with pytest.raises(ValueError, match="managed sentrix-build"):
        spec.validate()


def test_build_sandbox_accepts_dedicated_managed_name() -> None:
    BuildSandboxSpec(
        image="python:3.12-slim",
        command=("python", "-V"),
        network_name="sentrix-build-egress",
    ).validate()


@pytest.mark.parametrize("value", ["bridge", "host", "none", "default", "tenant-net", ""])
def test_safe_build_network_name_rejects_unmanaged_names(value: str) -> None:
    if value == "":
        # Empty environment means the secure dedicated default, not Docker bridge.
        assert network.safe_build_network_name(value) == network.DEFAULT_BUILD_NETWORK
    else:
        with pytest.raises(network.BuildNetworkError):
            network.safe_build_network_name(value)


def _worker_env(monkeypatch: pytest.MonkeyPatch, api_url: str) -> None:
    monkeypatch.setenv("SENTRIX_API_URL", api_url)
    monkeypatch.setenv("SENTRIX_CONTROL_WORKER_ID", "01920000-0000-7000-8000-000000000111")
    monkeypatch.setenv("SENTRIX_CONTROL_WORKER_TOKEN", "w" * 48)
    monkeypatch.setenv("SENTRIX_REGISTRY_PREFIX", "registry.example/sentrix")
    monkeypatch.delenv("SENTRIX_BUILD_NETWORK", raising=False)


def test_worker_config_defaults_to_managed_network(monkeypatch: pytest.MonkeyPatch) -> None:
    _worker_env(monkeypatch, "https://control.example")
    assert WorkerConfig.from_env().build_network == network.DEFAULT_BUILD_NETWORK


def test_worker_token_cannot_be_sent_over_remote_plain_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _worker_env(monkeypatch, "http://control.example")
    with pytest.raises(RuntimeError, match="HTTPS outside localhost"):
        WorkerConfig.from_env()


def test_local_http_remains_available_for_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    _worker_env(monkeypatch, "http://127.0.0.1:8000")
    assert WorkerConfig.from_env().api_url == "http://127.0.0.1:8000"


def test_registry_tag_is_fenced_by_build_and_lease_attempt() -> None:
    text = WORKER_SOURCE.read_text(encoding="utf-8")
    marker = "A lease-retried build must never share a mutable registry tag"
    assert marker in text
    section = text[text.index(marker) : text.index(marker) + 900]
    assert "job.lease_attempt" in section
    assert "job.build_id.hex" in section


def test_managed_network_is_created_and_policy_applied(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    egress = tmp_path / "apply-egress-policy.sh"
    egress.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    egress.chmod(0o700)

    def fake_run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[1:3] == ["network", "inspect"]:
            return subprocess.CompletedProcess(command, 1, "Error: No such network")
        return subprocess.CompletedProcess(command, 0, "")

    monkeypatch.setattr(network, "_run", fake_run)
    network.ensure_managed_build_network(
        network_name="sentrix-build-egress",
        docker_bin="docker",
        egress_script=egress,
        control_plane_cidrs="203.0.113.10/32",
    )

    create = next(command for command in calls if command[1:3] == ["network", "create"])
    assert "sentrix.managed=true" in create
    assert "sentrix.purpose=builder" in create
    assert "com.docker.network.bridge.enable_icc=false" in create
    assert calls[-1] == [str(egress), "docker", "203.0.113.10/32"]


def test_existing_unmanaged_network_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    egress = tmp_path / "apply-egress-policy.sh"
    egress.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    egress.chmod(0o700)

    def fake_run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "false\n")

    monkeypatch.setattr(network, "_run", fake_run)
    with pytest.raises(network.BuildNetworkError, match="unmanaged pre-existing"):
        network.ensure_managed_build_network(
            network_name="sentrix-build-egress",
            docker_bin="docker",
            egress_script=egress,
        )
