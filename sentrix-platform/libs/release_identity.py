"""Content-addressed identities used by SentriX releases (P2+)."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

_SHA256 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    """Immutable release content identity.

    A deployment is deliberately *not* identified by this key: redeploying the
    same release is legal and creates a fresh deployment UUID.
    """

    image_digest: str
    config_hash: str
    secret_version: int

    def __post_init__(self) -> None:
        digest = self.image_digest.removeprefix("sha256:")
        config = self.config_hash.removeprefix("sha256:")
        if not _SHA256.fullmatch(self.image_digest) and not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("image_digest must be a sha256 digest")
        if not _SHA256.fullmatch(self.config_hash) and not re.fullmatch(r"[0-9a-f]{64}", config):
            raise ValueError("config_hash must be a sha256 digest")
        if self.secret_version < 0:
            raise ValueError("secret_version must be non-negative")

    @property
    def stable_key(self) -> str:
        payload = f"{self.image_digest.removeprefix('sha256:')}:{self.config_hash.removeprefix('sha256:')}:{self.secret_version}"
        return hashlib.sha256(payload.encode()).hexdigest()


def hash_config(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
