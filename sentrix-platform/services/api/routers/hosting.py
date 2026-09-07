"""User-facing SentriX Cloud hosting API."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Annotated, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from libs import audit
from libs.ids import uuid7
from services.api.deps import AppState, OrgContext, get_state, map_pg_error, require_org
from services.api.routers.resources import DEFAULT_CELL
from services.builder_ctl.queue import BuildJob, BuildQueue
from services.secrets.runtime import KmsConfigurationError, cipher_from_env

router = APIRouter(prefix="/v1/orgs/{org_id}/hosting", tags=["hosting"])


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HostedServiceCreate(_StrictModel):
    name: str = Field(min_length=1, max_length=100)
    repo_full_name: str = Field(
        min_length=3,
        max_length=255,
        pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",
    )
    branch: str = Field(default="main", min_length=1, max_length=100)
    library: Literal["discordpy", "nextcord", "disnake"] = "discordpy"
    discord_application_id: str | None = Field(default=None, max_length=32)
    startup_command: list[str] = Field(default_factory=lambda: ["python", "main.py"], max_length=32)
    cpu_millis: int = Field(default=500, ge=50, le=4000)
    memory_mb: int = Field(default=256, ge=64, le=4096)
    pids_limit: int = Field(default=128, ge=16, le=1024)


class DeployRequest(_StrictModel):
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")


class SecretWrite(_StrictModel):
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Z][A-Z0-9_]*$")
    value: str = Field(min_length=1, max_length=16384)
    provider: Literal["tmpfs_file", "env"] = "tmpfs_file"


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _cache_key(repo: str, branch: str, commit_sha: str) -> str:
    raw = f"sentrix-cloud-v1\0{repo}\0{branch}\0{commit_sha}\0python3.12".encode()
    return hashlib.sha256(raw).hexdigest()


def _worker_configured() -> bool:
    try:
        UUID(os.environ.get("HOSTER_DEFAULT_NODE_ID", ""))
    except ValueError:
        return False
    return True


def _build_queue() -> BuildQueue:
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "file de build non configuree")
    return BuildQueue(redis_url)


@router.get("/overview")
async def overview(
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> dict[str, object]:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        counts = await conn.fetchrow(
            """
            SELECT
              (SELECT count(*) FROM environments WHERE status='active') AS services,
              (SELECT count(*) FROM instances WHERE desired_state='running') AS desired_running,
              (SELECT count(*) FROM instance_status WHERE observed_state='running') AS running,
              (SELECT count(*) FROM builds WHERE status IN ('queued','building','scanning')) AS builds,
              (SELECT count(*) FROM deployments WHERE status IN ('pending','running')) AS deployments
            """
        )
    return {
        **(dict(counts) if counts else {}),
        "worker": {
            "configured": _worker_configured(),
            "execution_plane": "external-gvisor",
            "control_plane_executes_user_code": False,
        },
    }


@router.post("/services", status_code=status.HTTP_201_CREATED)
async def create_service(
    payload: HostedServiceCreate,
    request: Request,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> dict[str, object]:
    project_id, bot_id, environment_id = uuid7(), uuid7(), uuid7()
    try:
        async with state.db.tenant_tx(ctx.org_id) as conn:
            await conn.execute(
                "INSERT INTO projects (id,org_id,name,repo_full_name,default_branch) "
                "VALUES ($1,$2,$3,$4,$5)",
                project_id,
                ctx.org_id,
                payload.name,
                payload.repo_full_name,
                payload.branch,
            )
            await conn.execute(
                "INSERT INTO bots (id,org_id,project_id,name,library) VALUES ($1,$2,$3,$4,$5)",
                bot_id,
                ctx.org_id,
                project_id,
                payload.name,
                payload.library,
            )
            await conn.execute(
                """
                INSERT INTO environments (
                    id,org_id,bot_id,kind,discord_application_id,cell_id,
                    runtime_mode,secret_provider
                ) VALUES ($1,$2,$3,'prod',$4,$5,'managed','tmpfs_file')
                """,
                environment_id,
                ctx.org_id,
                bot_id,
                payload.discord_application_id,
                DEFAULT_CELL,
            )
            await conn.execute(
                """
                INSERT INTO hosting_runtime_config (
                    environment_id,org_id,command,cpu_millis,memory_mb,pids_limit
                ) VALUES ($1,$2,$3::jsonb,$4,$5,$6)
                """,
                environment_id,
                ctx.org_id,
                json.dumps(payload.startup_command),
                payload.cpu_millis,
                payload.memory_mb,
                payload.pids_limit,
            )
            await audit.record(
                conn,
                org_id=ctx.org_id,
                actor_user_id=ctx.user_id,
                action="hosting.service.create",
                target_type="environment",
                target_id=environment_id,
                metadata={
                    "repo": payload.repo_full_name,
                    "branch": payload.branch,
                    "library": payload.library,
                    "cpu_millis": payload.cpu_millis,
                    "memory_mb": payload.memory_mb,
                },
                source_ip=_client_ip(request),
            )
    except asyncpg.PostgresError as exc:
        raise map_pg_error(exc) from exc
    return {
        "project_id": project_id,
        "bot_id": bot_id,
        "environment_id": environment_id,
        "state": "awaiting_deploy",
        "worker_configured": _worker_configured(),
    }


@router.get("/services")
async def list_services(
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> list[dict[str, object]]:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        rows = await conn.fetch(
            """
            SELECT e.id AS environment_id,b.id AS bot_id,p.id AS project_id,
                   b.name,b.library,p.repo_full_name,p.default_branch,
                   e.runtime_mode,e.secret_provider,e.created_at,
                   i.id AS instance_id,i.desired_state,s.observed_state,s.health,s.detail,
                   (SELECT status FROM builds bu WHERE bu.environment_id=e.id
                    ORDER BY bu.created_at DESC LIMIT 1) AS build_status,
                   (SELECT status FROM deployments d WHERE d.environment_id=e.id
                    ORDER BY d.created_at DESC LIMIT 1) AS deployment_status
              FROM environments e
              JOIN bots b ON b.id=e.bot_id
              JOIN projects p ON p.id=b.project_id
              LEFT JOIN instances i ON i.env_id=e.id
              LEFT JOIN instance_status s ON s.instance_id=i.id
             WHERE e.status='active' AND b.status='active' AND p.status='active'
             ORDER BY e.created_at DESC
            """
        )
    return [dict(row) for row in rows]


@router.get("/services/{environment_id}")
async def get_service(
    environment_id: UUID,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> dict[str, object]:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        row = await conn.fetchrow(
            """
            SELECT e.*,b.name,b.library,p.repo_full_name,p.default_branch,
                   i.id AS instance_id,i.desired_state,s.observed_state,s.health,s.detail,
                   s.updated_at AS status_updated_at
              FROM environments e
              JOIN bots b ON b.id=e.bot_id
              JOIN projects p ON p.id=b.project_id
              LEFT JOIN instances i ON i.env_id=e.id
              LEFT JOIN instance_status s ON s.instance_id=i.id
             WHERE e.id=$1
            """,
            environment_id,
        )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "service introuvable")
    return dict(row)


@router.post("/services/{environment_id}/deploy", status_code=status.HTTP_202_ACCEPTED)
async def queue_deploy(
    environment_id: UUID,
    payload: DeployRequest,
    request: Request,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> dict[str, object]:
    should_enqueue = False
    async with state.db.tenant_tx(ctx.org_id) as conn:
        source = await conn.fetchrow(
            """
            SELECT p.repo_full_name,p.default_branch
              FROM environments e JOIN bots b ON b.id=e.bot_id JOIN projects p ON p.id=b.project_id
             WHERE e.id=$1 AND e.status='active'
            """,
            environment_id,
        )
        if source is None or not source["repo_full_name"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "source GitHub introuvable")
        repo, branch = str(source["repo_full_name"]), str(source["default_branch"])
        key = _cache_key(repo, branch, payload.commit_sha)
        new_id = uuid7()
        row = await conn.fetchrow(
            """
            INSERT INTO builds (id,org_id,environment_id,commit_sha,cache_key)
            VALUES ($1,$2,$3,$4,$5)
            ON CONFLICT (org_id,environment_id,cache_key) DO NOTHING
            RETURNING id,status,commit_sha,created_at
            """,
            new_id,
            ctx.org_id,
            environment_id,
            payload.commit_sha,
            key,
        )
        if row is None:
            row = await conn.fetchrow(
                "SELECT id,status,commit_sha,created_at FROM builds "
                "WHERE environment_id=$1 AND cache_key=$2 FOR UPDATE",
                environment_id,
                key,
            )
            assert row is not None
            if row["status"] == "failed":
                row = await conn.fetchrow(
                    "UPDATE builds SET status='queued',error=NULL,updated_at=now() WHERE id=$1 "
                    "RETURNING id,status,commit_sha,created_at",
                    row["id"],
                )
                should_enqueue = True
        else:
            should_enqueue = True
        assert row is not None
        await audit.record(
            conn,
            org_id=ctx.org_id,
            actor_user_id=ctx.user_id,
            action="hosting.deploy.queue",
            target_type="build",
            target_id=row["id"],
            metadata={"environment_id": str(environment_id), "commit_sha": payload.commit_sha},
            source_ip=_client_ip(request),
        )

    if should_enqueue:
        queue = _build_queue()
        try:
            await queue.enqueue(
                BuildJob(
                    build_id=str(row["id"]),
                    org_id=str(ctx.org_id),
                    environment_id=str(environment_id),
                    repository=repo,
                    branch=branch,
                    commit_sha=payload.commit_sha,
                )
            )
        except Exception as exc:  # noqa: BLE001 - queue failure becomes durable build failure.
            async with state.db.tenant_tx(ctx.org_id) as conn:
                await conn.execute(
                    "UPDATE builds SET status='failed',error='queue unavailable',updated_at=now() "
                    "WHERE id=$1",
                    row["id"],
                )
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "file de build indisponible") from exc
        finally:
            await queue.close()

    message = "build deja disponible" if row["status"] == "succeeded" else "build en file"
    if not _worker_configured() and row["status"] != "succeeded":
        message += " ; worker gVisor a connecter"
    return {**dict(row), "worker_configured": _worker_configured(), "message": message}


@router.get("/services/{environment_id}/builds")
async def list_builds(
    environment_id: UUID,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> list[dict[str, object]]:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        rows = await conn.fetch(
            "SELECT id,commit_sha,status,image_digest,error,created_at,updated_at FROM builds "
            "WHERE environment_id=$1 ORDER BY created_at DESC LIMIT 50",
            environment_id,
        )
    return [dict(row) for row in rows]


@router.get("/services/{environment_id}/deployments")
async def list_deployments(
    environment_id: UUID,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> list[dict[str, object]]:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        rows = await conn.fetch(
            """
            SELECT id,release_id,previous_release_id,status,step,active_release_id,
                   error,created_at,updated_at
              FROM deployments WHERE environment_id=$1 ORDER BY created_at DESC LIMIT 50
            """,
            environment_id,
        )
    return [dict(row) for row in rows]


@router.get("/services/{environment_id}/secrets")
async def list_secret_metadata(
    environment_id: UUID,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> list[dict[str, object]]:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (name) name,provider,version,fingerprint,created_at,rotated_at
              FROM environment_secrets WHERE environment_id=$1 ORDER BY name,version DESC
            """,
            environment_id,
        )
    return [dict(row) for row in rows]


@router.put("/services/{environment_id}/secrets", status_code=status.HTTP_201_CREATED)
async def put_secret(
    environment_id: UUID,
    payload: SecretWrite,
    request: Request,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> dict[str, object]:
    try:
        cipher = cipher_from_env()
    except KmsConfigurationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    plaintext = payload.value.encode()
    fingerprint = hashlib.sha256(plaintext).hexdigest()[:16]
    async with state.db.tenant_tx(ctx.org_id) as conn:
        env = await conn.fetchrow(
            "SELECT id FROM environments WHERE id=$1 AND status='active' FOR UPDATE",
            environment_id,
        )
        if env is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "service introuvable")
        version = int(
            await conn.fetchval(
                "SELECT COALESCE(max(version),0)+1 FROM environment_secrets "
                "WHERE environment_id=$1 AND name=$2",
                environment_id,
                payload.name,
            )
        )
        envelope = cipher.encrypt(plaintext, environment_id=str(environment_id), version=version)
        row = await conn.fetchrow(
            """
            INSERT INTO environment_secrets (
                id,org_id,environment_id,name,provider,version,ciphertext,wrapped_dek,fingerprint
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            RETURNING name,provider,version,fingerprint,created_at
            """,
            uuid7(),
            ctx.org_id,
            environment_id,
            payload.name,
            payload.provider,
            version,
            envelope.ciphertext,
            envelope.wrapped_dek,
            fingerprint,
        )
        assert row is not None
        await audit.record(
            conn,
            org_id=ctx.org_id,
            actor_user_id=ctx.user_id,
            action="hosting.secret.rotate",
            target_type="environment",
            target_id=environment_id,
            metadata={
                "name": payload.name,
                "provider": payload.provider,
                "version": version,
                "fingerprint": fingerprint,
            },
            source_ip=_client_ip(request),
        )
    return {**dict(row), "value": None}


@router.get("/services/{environment_id}/usage")
async def usage(
    environment_id: UUID,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> list[dict[str, object]]:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        rows = await conn.fetch(
            """
            SELECT sampled_at,cpu_millis,memory_bytes,egress_bytes,log_bytes
              FROM usage_samples WHERE environment_id=$1 ORDER BY sampled_at DESC LIMIT 120
            """,
            environment_id,
        )
    return [dict(row) for row in rows]


async def _runtime_action(
    environment_id: UUID,
    action: Literal["start", "stop", "restart"],
    request: Request,
    ctx: OrgContext,
    state: AppState,
) -> dict[str, object]:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        instance = await conn.fetchrow(
            "SELECT id,desired_state,generation FROM instances WHERE env_id=$1",
            environment_id,
        )
        if instance is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "worker_not_assigned", "message": "aucun runtime gVisor assigne"},
            )
        desired = "stopped" if action == "stop" else "running"
        bump = action == "restart" or instance["desired_state"] != desired
        updated = instance
        if bump:
            updated = await conn.fetchrow(
                "UPDATE instances SET desired_state=$2,generation=generation+1,updated_at=now() "
                "WHERE id=$1 RETURNING id,desired_state,generation",
                instance["id"],
                desired,
            )
            assert updated is not None
        await audit.record(
            conn,
            org_id=ctx.org_id,
            actor_user_id=ctx.user_id,
            action=f"hosting.runtime.{action}",
            target_type="instance",
            target_id=instance["id"],
            metadata={"environment_id": str(environment_id)},
            source_ip=_client_ip(request),
        )
    return dict(updated)


@router.post("/services/{environment_id}/start")
async def start_service(
    environment_id: UUID,
    request: Request,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> dict[str, object]:
    return await _runtime_action(environment_id, "start", request, ctx, state)


@router.post("/services/{environment_id}/stop")
async def stop_service(
    environment_id: UUID,
    request: Request,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> dict[str, object]:
    return await _runtime_action(environment_id, "stop", request, ctx, state)


@router.post("/services/{environment_id}/restart")
async def restart_service(
    environment_id: UUID,
    request: Request,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> dict[str, object]:
    return await _runtime_action(environment_id, "restart", request, ctx, state)
