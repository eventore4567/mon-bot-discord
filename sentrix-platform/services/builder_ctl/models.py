from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BuildRequest:
    org_id: str
    repository: str
    commit_sha: str
    builder_image: str
    package_hosts: tuple[str, ...] = ()
    build_args: tuple[str, ...] = ()

    @property
    def cache_key(self) -> str:
        payload = "\0".join(
            (self.repository, self.commit_sha, self.builder_image, *self.build_args)
        )
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class BuildMount:
    source: str
    target: str
    read_only: bool = True

    def validate(self) -> None:
        source = Path(self.source)
        if not source.is_absolute():
            raise ValueError("build mount source must be absolute")
        if not self.target.startswith("/") or "\n" in self.target or "," in self.target:
            raise ValueError("invalid build mount target")
        if "\n" in self.source or "," in self.source:
            raise ValueError("invalid build mount source")


@dataclass(frozen=True, slots=True)
class BuildSandboxSpec:
    image: str
    command: tuple[str, ...]
    env: dict[str, str] = field(default_factory=dict)
    mounts: tuple[BuildMount, ...] = ()
    network_name: str = "none"
    memory_mb: int = 1024
    cpus: float = 1.0
    pids: int = 256

    def validate(self) -> None:
        forbidden = {"DISCORD_TOKEN", "DATABASE_URL", "REDIS_URL", "KMS_KEY", "GITHUB_TOKEN"}
        if forbidden.intersection(self.env):
            raise ValueError("tenant/control-plane secret present in build environment")
        if not self.command:
            raise ValueError("build command required")
        if not self.image or any(char.isspace() for char in self.image):
            raise ValueError("invalid build image")
        if not self.network_name or any(char.isspace() for char in self.network_name):
            raise ValueError("invalid build network")
        for mount in self.mounts:
            mount.validate()
