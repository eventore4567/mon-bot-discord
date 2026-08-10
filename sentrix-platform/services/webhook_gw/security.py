"""GitHub webhook authentication and delivery de-duplication (P2)."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Protocol


class WebhookAuthError(ValueError):
    pass


def verify_github_signature(body: bytes, signature: str | None, secret: bytes) -> None:
    """Verify ``X-Hub-Signature-256`` using constant-time comparison."""
    if not signature or not signature.startswith("sha256="):
        raise WebhookAuthError("missing or malformed github signature")
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise WebhookAuthError("invalid github signature")


class DeliveryDeduper(Protocol):
    async def claim(self, delivery_id: str) -> bool: ...


@dataclass
class MemoryDeliveryDeduper:
    """Test/dev implementation. Production uses the P2 Postgres table."""

    seen: set[str] = field(default_factory=set)

    async def claim(self, delivery_id: str) -> bool:
        if not delivery_id or len(delivery_id) > 128:
            raise ValueError("invalid delivery id")
        if delivery_id in self.seen:
            return False
        self.seen.add(delivery_id)
        return True
