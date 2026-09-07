"""Public GitHub webhook ingress for the Hosting build pipeline."""

from __future__ import annotations

import hashlib
import os
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from libs.ids import uuid7
from services.api.deps import AppState, get_state
from services.webhook_gw.security import DeliveryDeduper, WebhookAuthError
from services.webhook_gw.service import accept_push

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


class _DatabaseDeduper(DeliveryDeduper):
    """Validate delivery shape here; PostgreSQL is the authoritative deduper."""

    async def claim(self, delivery_id: str) -> bool:
        if not delivery_id or len(delivery_id) > 128:
            raise ValueError("invalid delivery id")
        return True


class GitHubPushResult(BaseModel):
    accepted: bool
    duplicate: bool = False
    ignored: bool = False
    queued_builds: int = 0


@router.post(
    "/github",
    response_model=GitHubPushResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def github_webhook(
    request: Request,
    state: Annotated[AppState, Depends(get_state)],
    signature: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
    delivery_id: Annotated[str | None, Header(alias="X-GitHub-Delivery")] = None,
    event: Annotated[str | None, Header(alias="X-GitHub-Event")] = None,
) -> GitHubPushResult:
    if event != "push":
        return GitHubPushResult(accepted=True, ignored=True)
    if delivery_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-GitHub-Delivery manquant")

    secret = os.environ.get("SENTRIX_GITHUB_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "webhook GitHub non configure")

    body = await request.body()
    try:
        push = await accept_push(
            body=body,
            signature=signature,
            delivery_id=delivery_id,
            webhook_secret=secret.encode("utf-8"),
            deduper=_DatabaseDeduper(),
        )
    except (WebhookAuthError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "webhook GitHub invalide") from exc

    if push is None:
        return GitHubPushResult(accepted=True, duplicate=True)

    async with state.db.admin_tx() as conn:
        rows = await conn.fetch(
            "SELECT * FROM public.sentrix_github_targets($1, $2)",
            push.repository,
            push.ref,
        )
    if not rows:
        return GitHubPushResult(accepted=True, ignored=True)

    org_ids = {UUID(str(row["org_id"])) for row in rows}
    if len(org_ids) != 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "repo GitHub ambigu entre organisations")
    org_id = next(iter(org_ids))

    queued = 0
    try:
        async with state.db.tenant_tx(org_id) as conn:
            inserted_delivery = await conn.fetchval(
                """
                INSERT INTO webhook_deliveries (
                    delivery_id, org_id, repository, event
                ) VALUES ($1, $2, $3, 'push')
                ON CONFLICT (delivery_id) DO NOTHING
                RETURNING delivery_id
                """,
                push.delivery_id,
                org_id,
                push.repository,
            )
            if inserted_delivery is None:
                return GitHubPushResult(accepted=True, duplicate=True)

            for row in rows:
                environment_id = UUID(str(row["environment_id"]))
                cache_key = hashlib.sha256(
                    f"{environment_id}:{push.commit_sha}".encode("utf-8")
                ).hexdigest()
                result = await conn.execute(
                    """
                    INSERT INTO builds (
                        id, org_id, environment_id, delivery_id,
                        commit_sha, cache_key, status
                    ) VALUES ($1, $2, $3, $4, $5, $6, 'queued')
                    ON CONFLICT (org_id, environment_id, cache_key) DO NOTHING
                    """,
                    uuid7(),
                    org_id,
                    environment_id,
                    push.delivery_id,
                    push.commit_sha,
                    cache_key,
                )
                if result.endswith(" 1"):
                    queued += 1
    except asyncpg.PostgresError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "push GitHub impossible a mettre en file") from exc

    return GitHubPushResult(accepted=True, queued_builds=queued)
