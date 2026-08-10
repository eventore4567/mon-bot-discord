"""Build-worker sandbox command construction.

The build worker is treated as hostile. It receives a minimal environment,
never a tenant secret, runs under gVisor and is always disposable.
"""

from __future__ import annotations

from services.builder_ctl.models import BuildSandboxSpec


def docker_command(name: str, spec: BuildSandboxSpec) -> list[str]:
    spec.validate()
    if not name.startswith("sx-build-"):
        raise ValueError("managed build container name required")
    cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--runtime=runsc",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--pids-limit",
        str(spec.pids),
        "--memory",
        f"{spec.memory_mb}m",
        "--memory-swap",
        f"{spec.memory_mb}m",
        "--cpus",
        str(spec.cpus),
        "--network",
        spec.network_name,
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=268435456",
        "--tmpfs",
        "/work:rw,nosuid,nodev,size=1073741824",
    ]
    for key, value in sorted(spec.env.items()):
        cmd.extend(["--env", f"{key}={value}"])
    cmd.append(spec.image)
    cmd.extend(spec.command)
    return cmd
