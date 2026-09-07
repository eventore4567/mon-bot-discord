"""Provider-neutral CRUD routes exposed in the public Hosting API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from libs import audit
from libs.ids import uuid7
from libs.models import ProjectCreate, ProjectOut
from services.api.deps import AppState, OrgContext, get_state, map_pg_error, require_org
from services.api.routers.resources import DEFAULT_CELL

router = APIRouter(prefix="/v1/workspaces/{org_id}", tags=["services"])

Runtime = Literal["python", "node", "docker"]
EnvironmentKind = Literal["prod", "canary"]
RuntimeMode = Literal["generic", "managed"]
SecretProvider = Literal["tmpfs_file", "env"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")


class ServiceCreate(_In):
    project_id: UUID
    name: str = Field(min_length=1, max_length=100)
    runtime: Runtime = "python"


class ServiceOut(_Out):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    name: str
    runtime: str
    status: str
    created_at: datetime


class HostingEnvironmentCreate(_In):
    service_id: UUID
    kind: EnvironmentKind = "prod"
    runtime_mode: RuntimeMode = "generic"
    secret_provider: SecretProvider = "tmpfs_file"


class HostingEnvironmentOut(_Out):
    id: UUID
    workspace_id: UUID
    service_id: UUID
    kind: str
    cell_id: UUID
    runtime_mode: str
    secret_provider: str
    status: str
    created_at: datetime


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _service_out(row: asyncpg.Record) -> ServiceOut:
    return ServiceOut(
        id=UUID(str(row["id"])),
        workspace_id=UUID(str(row["org_id"])),
        project_id=UUID(str(row["project_id"])),
        name=str(row["name"]),
        runtime=str(row["library"]),
        status=str(row["status"]),
        created_at=row["created_at"],
    )


def _environment_out(row: asyncpg.Record) -> HostingEnvironmentOut:
    return HostingEnvironmentOut(
        id=UUID(str(row["id"])),
        workspace_id=UUID(str(row["org_id"])),
        service_id=UUID(str(row["bot_id"])),
        kind=str(row["kind"]),
        cell_id=UUID(str(row["cell_id"])),
        runtime_mode=str(row["runtime_mode"]),
        secret_provider=str(row["secret_provider"]),
        status=str(row["status"]),
        created_at=row["created_at"],
    )


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    request: Request,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> ProjectOut:
    project_id = uuid7()
    try:
        async with state.db.tenant_tx(ctx.org_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO projects (id, org_id, name, repo_full_name, default_branch)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
                """,
                project_id,
                ctx.org_id,
                payload.name,
                payload.repo_full_name,
                payload.default_branch,
            )
            assert row is not None
            await audit.record(
                conn,
                org_id=ctx.org_id,
                actor_user_id=ctx.user_id,
                action="project.create",
                target_type="project",
                target_id=project_id,
                metadata={"name": payload.name},
                source_ip=_client_ip(request),
            )
    except asyncpg.PostgresError as exc:
        raise map_pg_error(exc) from exc
    return ProjectOut.model_validate(dict(row))


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> list[ProjectOut]:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        rows = await conn.fetch(
            "SELECT * FROM projects WHERE status = 'active' ORDER BY created_at DESC"
        )
    return [ProjectOut.model_validate(dict(row)) for row in rows]


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: UUID,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> ProjectOut:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        row = await conn.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ressource introuvable")
    return ProjectOut.model_validate(dict(row))


@router.post("/services", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
async def create_service(
    payload: ServiceCreate,
    request: Request,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> ServiceOut:
    service_id = uuid7()
    try:
        async with state.db.tenant_tx(ctx.org_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO bots (id, org_id, project_id, name, library)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
                """,
                service_id,
                ctx.org_id,
                payload.project_id,
                payload.name,
                payload.runtime,
            )
            assert row is not None
            await audit.record(
                conn,
                org_id=ctx.org_id,
                actor_user_id=ctx.user_id,
                action="service.create",
                target_type="service",
                target_id=service_id,
                metadata={"name": payload.name, "runtime": payload.runtime},
                source_ip=_client_ip(request),
            )
    except asyncpg.PostgresError as exc:
        raise map_pg_error(exc) from exc
    return _service_out(row)


@router.get("/services", response_model=list[ServiceOut])
async def list_services(
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> list[ServiceOut]:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        rows = await conn.fetch(
            "SELECT * FROM bots WHERE status = 'active' ORDER BY created_at DESC"
        )
    return [_service_out(row) for row in rows]


@router.get("/services/{service_id}", response_model=ServiceOut)
async def get_service(
    service_id: UUID,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> ServiceOut:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        row = await conn.fetchrow("SELECT * FROM bots WHERE id = $1", service_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ressource introuvable")
    return _service_out(row)


@router.post(
    "/environments",
    response_model=HostingEnvironmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_environment(
    payload: HostingEnvironmentCreate,
    request: Request,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> HostingEnvironmentOut:
    environment_id = uuid7()
    try:
        async with state.db.tenant_tx(ctx.org_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO environments
                    (id, org_id, bot_id, kind, discord_application_id,
                     cell_id, runtime_mode, secret_provider)
                VALUES ($1, $2, $3, $4, NULL, $5, $6, $7)
                RETURNING *
                """,
                environment_id,
                ctx.org_id,
                payload.service_id,
                payload.kind,
                DEFAULT_CELL,
                payload.runtime_mode,
                payload.secret_provider,
            )
            assert row is not None
            await audit.record(
                conn,
                org_id=ctx.org_id,
                actor_user_id=ctx.user_id,
                action="environment.create",
                target_type="environment",
                target_id=environment_id,
                metadata={"kind": payload.kind, "runtime_mode": payload.runtime_mode},
                source_ip=_client_ip(request),
            )
    except asyncpg.PostgresError as exc:
        raise map_pg_error(exc) from exc
    return _environment_out(row)


@router.get("/environments", response_model=list[HostingEnvironmentOut])
async def list_environments(
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> list[HostingEnvironmentOut]:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        rows = await conn.fetch(
            "SELECT * FROM environments WHERE status = 'active' ORDER BY created_at DESC"
        )
    return [_environment_out(row) for row in rows]


@router.get("/environments/{environment_id}", response_model=HostingEnvironmentOut)
async def get_environment(
    environment_id: UUID,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> HostingEnvironmentOut:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        row = await conn.fetchrow("SELECT * FROM environments WHERE id = $1", environment_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ressource introuvable")
    return _environment_out(row)
