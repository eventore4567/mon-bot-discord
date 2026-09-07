"""Private HTTP bridge between SentriX Control Plane and build workers."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from libs.ids import uuid7
from libs.release_identity import ReleaseIdentity, hash_config
from services.api.deps import AppState
from services.builder_ctl.queue import BuildQueue

router = APIRouter(prefix="/v1/internal/builder", tags=["builder-internal"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BuildComplete(_Strict):
    message_id: str = Field(min_length=3, max_length=128)
    build_id: UUID
    org_id: UUID
    environment_id: UUID
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class BuildFailed(_Strict):
    message_id: str = Field(min_length=3, max_length=128)
    build_id: UUID
    org_id: UUID
    environment_id: UUID
    error: str = Field(min_length=1, max_length=2000)


def _builder_token() -> str:
    return os.environ.get("HOSTER_BUILDER_TOKEN", "")


def _authorize(raw: str) -> None:
    expected = _builder_token()
    if not expected or not hmac.compare_digest(raw, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "builder non autorise")


def _queue() -> BuildQueue:
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "file builder non configuree")
    return BuildQueue(redis_url)


def _default_node_id() -> UUID | None:
    try:
        return UUID(os.environ.get("HOSTER_DEFAULT_NODE_ID", ""))
    except ValueError:
        return None


def _config_hash(command: list[str], cpu: int, memory: int, pids: int) -> str:
    payload = json.dumps(
        {"command": command, "cpu_millis": cpu, "memory_mb": memory, "pids_limit": pids},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hash_config(payload)


def install_builder_routes(app_state: AppState) -> None:
    """Compatibility hook retained for explicit startup wiring/tests."""
    del app_state


@router.get("/claim")
async def claim_build(
    worker_id: Annotated[str, Query(min_length=1, max_length=100)],
    builder_token: Annotated[
        str,
        Header(alias="X-Sentrix-Builder-Token", min_length=32, max_length=512),
    ],
) -> dict[str, object]:
    _authorize(builder_token)
    queue = _queue()
    try:
        claim = await queue.claim(worker_id)
    finally:
        await queue.close()
    if claim is None:
        return {"job": None}

    # The worker receives only public source coordinates and opaque tenant ids.
    return {
        "message_id": claim.message_id,
        "job": {
            "build_id": claim.job.build_id,
            "org_id": claim.job.org_id,
            "environment_id": claim.job.environment_id,
            "repository": claim.job.repository,
            "branch": claim.job.branch,
            "commit_sha": claim.job.commit_sha,
        },
    }


@router.post("/complete")
async def complete_build(
    payload: BuildComplete,
    builder_token: Annotated[
        str,
        Header(alias="X-Sentrix-Builder-Token", min_length=32, max_length=512),
    ],
    state: AppState,
) -> dict[str, object]:
    _authorize(builder_token)
    node_id = _default_node_id()
    deployment_id: UUID | None = None
    instance_id: UUID | None = None

    async with state.db.tenant_tx(payload.org_id) as conn:
        build = await conn.fetchrow(
            """
            SELECT id, environment_id, status
              FROM builds
             WHERE id = $1 AND environment_id = $2
             FOR UPDATE
            """,
            payload.build_id,
            payload.environment_id,
        )
        if build is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "build introuvable")

        await conn.execute(
            """
            UPDATE builds
               SET status = 'succeeded', image_digest = $2, error = NULL, updated_at = now()
             WHERE id = $1
            """,
            payload.build_id,
            payload.image_digest,
        )

        config = await conn.fetchrow(
            """
            SELECT command, cpu_millis, memory_mb, pids_limit
              FROM hosting_runtime_config
             WHERE environment_id = $1
            """,
            payload.environment_id,
        )
        command = list(config["command"]) if config is not None else ["python", "main.py"]
        cpu = int(config["cpu_millis"]) if config is not None else 500
        memory = int(config["memory_mb"]) if config is not None else 256
        pids = int(config["pids_limit"]) if config is not None else 128
        secret_version = int(
            await conn.fetchval(
                "SELECT COALESCE(max(version), 0) FROM environment_secrets WHERE environment_id = $1",
                payload.environment_id,
            )
            or 0
        )
        identity = ReleaseIdentity(
            payload.image_digest,
            _config_hash(command, cpu, memory, pids),
            secret_version,
        )
        release = await conn.fetchrow(
            "SELECT id FROM releases WHERE environment_id = $1 AND identity_key = $2",
            payload.environment_id,
            identity.stable_key,
        )
        if release is None:
            release_id = uuid7()
            await conn.execute(
                """
                INSERT INTO releases (
                    id, org_id, environment_id, build_id, image_digest,
                    config_hash, secret_version, identity_key
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                """,
                release_id,
                payload.org_id,
                payload.environment_id,
                payload.build_id,
                payload.image_digest,
                identity.config_hash,
                identity.secret_version,
                identity.stable_key,
            )
        else:
            release_id = release["id"]

        if node_id is not None:
            existing = await conn.fetchrow(
                "SELECT id FROM instances WHERE env_id = $1",
                payload.environment_id,
            )
            if existing is None:
                instance_id = uuid7()
                await conn.execute(
                    """
                    INSERT INTO instances (
                        id, org_id, env_id, cell_id, node_id, desired_state,
                        image_ref, command, cpu_millis, memory_mb, pids_limit
                    )
                    SELECT $1,$2,e.id,e.cell_id,$3,'running',$4,$5::jsonb,$6,$7,$8
                      FROM environments e WHERE e.id = $9
                    """,
                    instance_id,
                    payload.org_id,
                    node_id,
                    payload.image_digest,
                    json.dumps(command),
                    cpu,
                    memory,
                    pids,
                    payload.environment_id,
                )
            else:
                instance_id = existing["id"]
                await conn.execute(
                    """
                    UPDATE instances
                       SET node_id = $2, desired_state = 'running', image_ref = $3,
                           command = $4::jsonb, cpu_millis = $5, memory_mb = $6,
                           pids_limit = $7, generation = generation + 1, updated_at = now()
                     WHERE id = $1
                    """,
                    instance_id,
                    node_id,
                    payload.image_digest,
                    json.dumps(command),
                    cpu,
                    memory,
                    pids,
                )

            previous = await conn.fetchval(
                """
                SELECT active_release_id
                  FROM deployments
                 WHERE environment_id = $1 AND active_release_id IS NOT NULL
                 ORDER BY created_at DESC LIMIT 1
                """,
                payload.environment_id,
            )
            deployment_id = uuid7()
            idempotency_key = hashlib.sha256(
                f"hoster:{payload.build_id}:{release_id}:{instance_id}".encode()
            ).hexdigest()
            existing_dep = await conn.fetchrow(
                "SELECT id FROM deployments WHERE idempotency_key = $1",
                idempotency_key,
            )
            if existing_dep is None:
                await conn.execute(
                    """
                    INSERT INTO deployments (
                        id, org_id, environment_id, release_id, previous_release_id,
                        idempotency_key, status, step, active_release_id
                    ) VALUES ($1,$2,$3,$4,$5,$6,'running','health',$4)
                    """,
                    deployment_id,
                    payload.org_id,
                    payload.environment_id,
                    release_id,
                    previous,
                    idempotency_key,
                )
            else:
                deployment_id = existing_dep["id"]

    queue = _queue()
    try:
        await queue.ack(payload.message_id)
    finally:
        await queue.close()
    return {
        "ok": True,
        "release_id": release_id,
        "deployment_id": deployment_id,
        "instance_id": instance_id,
        "runtime_assigned": node_id is not None,
    }


@router.post("/failed", status_code=status.HTTP_204_NO_CONTENT)
async def fail_build(
    payload: BuildFailed,
    builder_token: Annotated[
        str,
        Header(alias="X-Sentrix-Builder-Token", min_length=32, max_length=512),
    ],
    state: AppState,
) -> None:
    _authorize(builder_token)
    async with state.db.tenant_tx(payload.org_id) as conn:
        result = await conn.execute(
            """
            UPDATE builds SET status = 'failed', error = $3, updated_at = now()
             WHERE id = $1 AND environment_id = $2
            """,
            payload.build_id,
            payload.environment_id,
            payload.error,
        )
    if result == "UPDATE 0":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "build introuvable")
    queue = _queue()
    try:
        await queue.ack(payload.message_id)
    finally:
        await queue.close()
