"""Product-facing Hosting V1 API.

This router turns the lower-level P0-P6 primitives into a small, coherent
hosting workflow. It remains tenant-scoped through ``tenant_tx`` and never
returns secret ciphertext or plaintext.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from libs import audit
from libs.ids import uuid7
from services.api.deps import AppState, OrgContext, get_state, map_pg_error, require_org

router = APIRouter(prefix="/v1/orgs/{org_id}/hosting", tags=["hosting"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


class BuildRequest(BaseModel):
    environment_id: UUID
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")


class BuildOut(BaseModel):
    id: UUID
    environment_id: UUID
    commit_sha: str
    status: str
    image_digest: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class ReleaseOut(BaseModel):
    id: UUID
    environment_id: UUID
    build_id: UUID | None = None
    image_digest: str
    config_hash: str
    secret_version: int
    created_at: datetime


class DeployRequest(BaseModel):
    release_id: UUID


class DeploymentOut(BaseModel):
    id: UUID
    environment_id: UUID
    release_id: UUID
    previous_release_id: UUID | None = None
    status: str
    step: str
    active_release_id: UUID | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class RuntimeAction(BaseModel):
    action: Literal["start", "stop", "restart"]


class RuntimeActionOut(BaseModel):
    environment_id: UUID
    action: str
    affected_instances: int
    desired_state: str


class SecretMetadata(BaseModel):
    name: str
    provider: str
    version: int
    fingerprint: str
    created_at: datetime
    rotated_at: datetime | None = None


class UsageOut(BaseModel):
    sampled_at: datetime
    cpu_millis: int
    memory_bytes: int
    egress_bytes: int
    log_bytes: int


class HostingOverview(BaseModel):
    projects: int
    bots: int
    environments: int
    running_instances: int
    queued_builds: int
    active_deployments: int


def _cache_key(environment_id: UUID, commit_sha: str) -> str:
    raw = f"sentrix-hosting-v1:{environment_id}:{commit_sha}".encode()
    return hashlib.sha256(raw).hexdigest()


@router.get("/overview", response_model=HostingOverview)
async def overview(
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> HostingOverview:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        row = await conn.fetchrow(
            """
            SELECT
              (SELECT count(*) FROM projects WHERE status = 'active') AS projects,
              (SELECT count(*) FROM bots WHERE status = 'active') AS bots,
              (SELECT count(*) FROM environments WHERE status = 'active') AS environments,
              (SELECT count(*) FROM instances WHERE desired_state = 'running') AS running_instances,
              (SELECT count(*) FROM builds WHERE status IN ('queued','building','scanning')) AS queued_builds,
              (SELECT count(*) FROM deployments WHERE status IN ('pending','running')) AS active_deployments
            """
        )
    assert row is not None
    return HostingOverview(**dict(row))


@router.post("/builds", response_model=BuildOut, status_code=status.HTTP_202_ACCEPTED)
async def queue_build(
    payload: BuildRequest,
    request: Request,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> BuildOut:
    """Queue an immutable build for an environment.

    The builder controller consumes rows in ``queued`` state. The cache key is
    deterministic, so retrying the same commit cannot create a build storm.
    """
    build_id = uuid7()
    cache_key = _cache_key(payload.environment_id, payload.commit_sha)
    try:
        async with state.db.tenant_tx(ctx.org_id) as conn:
            env = await conn.fetchval(
                "SELECT id FROM environments WHERE id = $1 AND status = 'active'",
                payload.environment_id,
            )
            if env is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "environnement introuvable")

            row = await conn.fetchrow(
                """
                INSERT INTO builds (id, org_id, environment_id, commit_sha, cache_key)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (org_id, environment_id, cache_key)
                DO UPDATE SET updated_at = builds.updated_at
                RETURNING id, environment_id, commit_sha, status, image_digest,
                          error, created_at, updated_at
                """,
                build_id,
                ctx.org_id,
                payload.environment_id,
                payload.commit_sha,
                cache_key,
            )
            assert row is not None
            await audit.record(
                conn,
                org_id=ctx.org_id,
                actor_user_id=ctx.user_id,
                action="hosting.build.queue",
                target_type="build",
                target_id=row["id"],
                metadata={
                    "environment_id": str(payload.environment_id),
                    "commit_sha": payload.commit_sha,
                },
                source_ip=_client_ip(request),
            )
    except asyncpg.PostgresError as exc:
        raise map_pg_error(exc) from exc
    return BuildOut.model_validate(dict(row))


@router.get("/builds", response_model=list[BuildOut])
async def list_builds(
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
    environment_id: UUID | None = None,
    limit: int = 50,
) -> list[BuildOut]:
    limit = max(1, min(limit, 100))
    async with state.db.tenant_tx(ctx.org_id) as conn:
        rows = await conn.fetch(
            """
            SELECT id, environment_id, commit_sha, status, image_digest,
                   error, created_at, updated_at
              FROM builds
             WHERE ($1::uuid IS NULL OR environment_id = $1)
             ORDER BY created_at DESC
             LIMIT $2
            """,
            environment_id,
            limit,
        )
    return [BuildOut.model_validate(dict(row)) for row in rows]


@router.get("/releases", response_model=list[ReleaseOut])
async def list_releases(
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
    environment_id: UUID | None = None,
    limit: int = 50,
) -> list[ReleaseOut]:
    limit = max(1, min(limit, 100))
    async with state.db.tenant_tx(ctx.org_id) as conn:
        rows = await conn.fetch(
            """
            SELECT id, environment_id, build_id, image_digest, config_hash,
                   secret_version, created_at
              FROM releases
             WHERE ($1::uuid IS NULL OR environment_id = $1)
             ORDER BY created_at DESC
             LIMIT $2
            """,
            environment_id,
            limit,
        )
    return [ReleaseOut.model_validate(dict(row)) for row in rows]


@router.post("/deployments", response_model=DeploymentOut, status_code=status.HTTP_202_ACCEPTED)
async def queue_deployment(
    payload: DeployRequest,
    request: Request,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> DeploymentOut:
    deployment_id = uuid7()
    try:
        async with state.db.tenant_tx(ctx.org_id) as conn:
            release = await conn.fetchrow(
                "SELECT id, environment_id FROM releases WHERE id = $1",
                payload.release_id,
            )
            if release is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "release introuvable")
            environment_id = release["environment_id"]
            previous_release_id = await conn.fetchval(
                """
                SELECT active_release_id
                  FROM deployments
                 WHERE environment_id = $1
                   AND status = 'succeeded'
                   AND active_release_id IS NOT NULL
                 ORDER BY updated_at DESC
                 LIMIT 1
                """,
                environment_id,
            )
            idempotency_key = f"ui:{environment_id}:{payload.release_id}"
            row = await conn.fetchrow(
                """
                INSERT INTO deployments (
                    id, org_id, environment_id, release_id,
                    previous_release_id, idempotency_key
                ) VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (org_id, idempotency_key)
                DO UPDATE SET updated_at = deployments.updated_at
                RETURNING id, environment_id, release_id, previous_release_id,
                          status, step, active_release_id, error, created_at, updated_at
                """,
                deployment_id,
                ctx.org_id,
                environment_id,
                payload.release_id,
                previous_release_id,
                idempotency_key,
            )
            assert row is not None
            await audit.record(
                conn,
                org_id=ctx.org_id,
                actor_user_id=ctx.user_id,
                action="hosting.deploy.queue",
                target_type="deployment",
                target_id=row["id"],
                metadata={"release_id": str(payload.release_id)},
                source_ip=_client_ip(request),
            )
    except asyncpg.PostgresError as exc:
        raise map_pg_error(exc) from exc
    return DeploymentOut.model_validate(dict(row))


@router.get("/deployments", response_model=list[DeploymentOut])
async def list_deployments(
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
    environment_id: UUID | None = None,
    limit: int = 50,
) -> list[DeploymentOut]:
    limit = max(1, min(limit, 100))
    async with state.db.tenant_tx(ctx.org_id) as conn:
        rows = await conn.fetch(
            """
            SELECT id, environment_id, release_id, previous_release_id,
                   status, step, active_release_id, error, created_at, updated_at
              FROM deployments
             WHERE ($1::uuid IS NULL OR environment_id = $1)
             ORDER BY created_at DESC
             LIMIT $2
            """,
            environment_id,
            limit,
        )
    return [DeploymentOut.model_validate(dict(row)) for row in rows]


@router.post("/environments/{environment_id}/runtime", response_model=RuntimeActionOut)
async def runtime_action(
    environment_id: UUID,
    payload: RuntimeAction,
    request: Request,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> RuntimeActionOut:
    desired = "stopped" if payload.action == "stop" else "running"
    async with state.db.tenant_tx(ctx.org_id) as conn:
        exists = await conn.fetchval("SELECT 1 FROM environments WHERE id = $1", environment_id)
        if exists is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "environnement introuvable")

        # Restart is represented by a new generation while keeping desired=running;
        # agents reconcile the generation change instead of exposing Docker directly.
        rows = await conn.fetch(
            """
            UPDATE instances
               SET desired_state = $2,
                   generation = generation + 1,
                   updated_at = now()
             WHERE env_id = $1
            RETURNING id
            """,
            environment_id,
            desired,
        )
        await audit.record(
            conn,
            org_id=ctx.org_id,
            actor_user_id=ctx.user_id,
            action=f"hosting.runtime.{payload.action}",
            target_type="environment",
            target_id=environment_id,
            metadata={"affected_instances": len(rows)},
            source_ip=_client_ip(request),
        )
    return RuntimeActionOut(
        environment_id=environment_id,
        action=payload.action,
        affected_instances=len(rows),
        desired_state=desired,
    )


@router.get("/environments/{environment_id}/secrets", response_model=list[SecretMetadata])
async def list_secret_metadata(
    environment_id: UUID,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> list[SecretMetadata]:
    """Return metadata only; ciphertext, wrapped DEKs and values never leave storage."""
    async with state.db.tenant_tx(ctx.org_id) as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (name)
                   name, provider, version, fingerprint, created_at, rotated_at
              FROM environment_secrets
             WHERE environment_id = $1
             ORDER BY name, version DESC
            """,
            environment_id,
        )
    return [SecretMetadata.model_validate(dict(row)) for row in rows]


@router.get("/environments/{environment_id}/usage", response_model=list[UsageOut])
async def usage(
    environment_id: UUID,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
    limit: int = 120,
) -> list[UsageOut]:
    limit = max(1, min(limit, 500))
    async with state.db.tenant_tx(ctx.org_id) as conn:
        rows = await conn.fetch(
            """
            SELECT sampled_at, cpu_millis, memory_bytes, egress_bytes, log_bytes
              FROM usage_samples
             WHERE environment_id = $1
             ORDER BY sampled_at DESC
             LIMIT $2
            """,
            environment_id,
            limit,
        )
    return [UsageOut.model_validate(dict(row)) for row in rows]
