from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from services.builder_ctl import network
from services.builder_ctl.models import BuildSandboxSpec


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
