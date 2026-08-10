"""Secret lifecycle service: write-only API semantics, rotation and audit."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path

from services.secrets.crypto import EnvelopeCipher, SecretEnvelope


@dataclass(slots=True)
class StoredSecret:
    environment_id: str
    name: str
    envelope: SecretEnvelope
    fingerprint: str
    provider: str

    def public_view(self) -> dict[str, object]:
        return {
            "environment_id": self.environment_id,
            "name": self.name,
            "version": self.envelope.version,
            "provider": self.provider,
            "fingerprint": self.fingerprint,
            "value": None,
        }


@dataclass
class SecretService:
    cipher: EnvelopeCipher
    values: dict[tuple[str, str], StoredSecret] = field(default_factory=dict)
    audit: list[dict[str, object]] = field(default_factory=list)

    def put(self, environment_id: str, name: str, plaintext: bytes, *, provider: str) -> StoredSecret:
        if provider not in {"tmpfs_file", "env"}:
            raise ValueError("unknown secret provider")
        if not plaintext:
            raise ValueError("empty secret")
        previous = self.values.get((environment_id, name))
        version = 1 if previous is None else previous.envelope.version + 1
        envelope = self.cipher.encrypt(plaintext, environment_id=environment_id, version=version)
        fingerprint = hashlib.sha256(plaintext).hexdigest()[:16]
        stored = StoredSecret(environment_id, name, envelope, fingerprint, provider)
        self.values[(environment_id, name)] = stored
        self.audit.append({"action": "secret.put", "environment_id": environment_id, "name": name, "version": version})
        return stored

    def materialize(self, environment_id: str, name: str, *, actor: str) -> bytes:
        stored = self.values[(environment_id, name)]
        self.audit.append({
            "action": "secret.access",
            "environment_id": environment_id,
            "name": name,
            "version": stored.envelope.version,
            "actor": actor,
        })
        return self.cipher.decrypt(stored.envelope, environment_id=environment_id)


@dataclass(frozen=True, slots=True)
class TmpfsSecretSpec:
    container_path: str
    mode: int = 0o400


def write_tmpfs_secret(root: Path, spec: TmpfsSecretSpec, value: bytes) -> Path:
    """Write to an already-mounted tmpfs directory.

    The caller is responsible for mounting ``root`` as tmpfs. The helper refuses
    symlink traversal and writes atomically with owner-only permissions.
    """
    root = root.resolve()
    relative = spec.container_path.lstrip("/")
    target = (root / relative).resolve()
    if root not in target.parents:
        raise ValueError("secret path escapes tmpfs root")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, spec.mode)
    try:
        os.write(fd, value)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(target, spec.mode)
    return target


def provider_exposure(provider: str) -> str:
    if provider == "tmpfs_file":
        return "low: file on tmpfs; absent from process environment and docker inspect"
    if provider == "env":
        return "high: process environment compatibility mode"
    raise ValueError("unknown provider")
