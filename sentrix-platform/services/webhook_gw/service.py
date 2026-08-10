"""Small transport-neutral webhook gateway core."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from services.webhook_gw.security import DeliveryDeduper, verify_github_signature


@dataclass(frozen=True, slots=True)
class AcceptedPush:
    delivery_id: str
    repository: str
    commit_sha: str
    ref: str


async def accept_push(
    *,
    body: bytes,
    signature: str | None,
    delivery_id: str,
    webhook_secret: bytes,
    deduper: DeliveryDeduper,
) -> AcceptedPush | None:
    verify_github_signature(body, signature, webhook_secret)
    if not await deduper.claim(delivery_id):
        return None
    payload: dict[str, Any] = json.loads(body)
    repo = payload.get("repository", {}).get("full_name")
    sha = payload.get("after")
    ref = payload.get("ref")
    if not isinstance(repo, str) or not isinstance(sha, str) or not isinstance(ref, str):
        raise ValueError("unsupported github push payload")
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha.lower()):
        raise ValueError("invalid commit sha")
    return AcceptedPush(delivery_id, repo, sha.lower(), ref)
