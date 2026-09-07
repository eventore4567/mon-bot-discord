"""Fail-closed network preparation for untrusted dependency builds.

Dependency installers need public Internet access, but they must never be able to
reach cloud metadata, private infrastructure or the SentriX control plane through
Docker's unmanaged default bridge.  This module creates a dedicated managed
bridge and applies the host-level egress policy before any build sandbox starts.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

DEFAULT_BUILD_NETWORK = "sentrix-build-egress"
_NETWORK_NAME = re.compile(r"^sentrix-build-[a-z0-9][a-z0-9_.-]{0,47}$")
_RESERVED_NETWORKS = frozenset({"bridge", "host", "none", "default"})


class BuildNetworkError(RuntimeError):
    """Raised when the dependency sandbox network cannot be proven safe."""


def safe_build_network_name(value: str | None) -> str:
    name = (value or DEFAULT_BUILD_NETWORK).strip().lower()
    if name in _RESERVED_NETWORKS or not _NETWORK_NAME.fullmatch(name):
        raise BuildNetworkError(
            "SENTRIX_BUILD_NETWORK must be a dedicated name starting with 'sentrix-build-'"
        )
    return name


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    if not command:
        raise BuildNetworkError("empty network command")
    binary = shutil.which(command[0])
    if binary is None:
        raise BuildNetworkError(f"required executable missing: {command[0]}")
    completed = subprocess.run(  # noqa: S603 - argv only, never a shell
        [binary, *command[1:]],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=60,
    )
    if check and completed.returncode != 0:
        output = completed.stdout[-4000:].strip()
        raise BuildNetworkError(
            f"network command failed ({command[0]}, exit={completed.returncode}): {output}"
        )
    return completed


def ensure_managed_build_network(
    *,
    network_name: str,
    docker_bin: str = "docker",
    egress_script: Path,
    control_plane_cidrs: str = "",
) -> None:
    """Create/verify the managed bridge and apply egress policy before builds."""

    name = safe_build_network_name(network_name)
    inspect = _run(
        [
            docker_bin,
            "network",
            "inspect",
            "--format",
            '{{ index .Labels "sentrix.managed" }}',
            name,
        ],
        check=False,
    )
    if inspect.returncode != 0:
        _run(
            [
                docker_bin,
                "network",
                "create",
                "--driver",
                "bridge",
                "--opt",
                "com.docker.network.bridge.enable_icc=false",
                "--label",
                "sentrix.managed=true",
                "--label",
                "sentrix.purpose=builder",
                name,
            ]
        )
    elif inspect.stdout.strip().lower() != "true":
        raise BuildNetworkError(f"refusing unmanaged pre-existing Docker network: {name}")

    if not egress_script.is_absolute() or not egress_script.is_file():
        raise BuildNetworkError(f"egress policy script missing: {egress_script}")
    if not os.access(egress_script, os.X_OK):
        raise BuildNetworkError(f"egress policy script is not executable: {egress_script}")

    # The policy script itself fails closed when DOCKER-USER/iptables is absent.
    _run([str(egress_script), docker_bin, control_plane_cidrs])


def prepare_from_env() -> str:
    """Prepare the production build network and return the validated name."""

    name = safe_build_network_name(os.environ.get("SENTRIX_BUILD_NETWORK"))
    egress_script = Path(
        os.environ.get(
            "SENTRIX_EGRESS_SCRIPT",
            "/opt/sentrix-platform/ops/execution/apply-egress-policy.sh",
        )
    )
    ensure_managed_build_network(
        network_name=name,
        docker_bin=os.environ.get("SENTRIX_DOCKER_BIN", "docker"),
        egress_script=egress_script,
        control_plane_cidrs=os.environ.get("SENTRIX_CONTROL_PLANE_CIDRS", ""),
    )
    # WorkerConfig reads this environment variable afterwards.  Setting the
    # validated value here prevents its historical unsafe "bridge" default from
    # being reachable through the standard production entrypoint.
    os.environ["SENTRIX_BUILD_NETWORK"] = name
    return name
