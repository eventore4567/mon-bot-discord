"""P2 build orchestration core, independent from the HTTP transport."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from libs.release_identity import ReleaseIdentity, hash_config
from services.builder_ctl.models import BuildRequest
from services.builder_ctl.scanner import SecretFinding, scan_tree


class BuildRejected(RuntimeError):
    def __init__(self, findings: list[SecretFinding]) -> None:
        super().__init__("source scan rejected build")
        self.findings = findings


class Registry(Protocol):
    async def immutable_digest(self, image_ref: str) -> str: ...


@dataclass
class BuildCache:
    values: dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def put(self, key: str, digest: str) -> None:
        self.values[key] = digest


def preflight_source(root: Path) -> None:
    findings = scan_tree(root)
    if findings:
        raise BuildRejected(findings)


def make_release_identity(*, digest: str, config: bytes, secret_version: int) -> ReleaseIdentity:
    return ReleaseIdentity(digest, hash_config(config), secret_version)


def sanitized_build_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Builds start from an allowlist, never from ``os.environ``."""
    env = {
        "HOME": "/tmp/home",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "CI": "1",
    }
    if extra:
        for key, value in extra.items():
            if key.startswith(("SENTRIX_", "DISCORD_")) or key in {"DATABASE_URL", "REDIS_URL", "GITHUB_TOKEN"}:
                raise ValueError(f"forbidden build environment key: {key}")
            env[key] = value
    return env


def cache_lookup(cache: BuildCache, request: BuildRequest) -> str | None:
    return cache.get(request.cache_key)
