"""CRUD minimal P1 pour l'etat desire des instances."""

from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status

from libs import audit
from libs.ids import uuid7
from libs.runtime_models import (
    InstanceCreate,
    InstanceDesiredUpdate,
    InstanceOut,
    InstanceStatusOut,
)
from services.api.deps import AppState, OrgContext, get_state, map_pg_error, require_org

router = APIRouter(prefix="/v1/orgs/{org_id}", tags=["instances"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/instances", response_model=InstanceOut, status_code=status.HTTP_201_CREATED)
async def create_instance(
    payload: InstanceCreate,
    request: Request,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> InstanceOut:
    instance_id = uuid7()
    try:
        async with state.db.tenant_tx(ctx.org_id) as conn:
            env = await conn.fetchrow(
                "SELECT cell_id FROM environments WHERE id = $1 AND status = 'active'",
                payload.environment_id,
            )
            if env is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "environnement introuvable")
            row = await conn.fetchrow(
                """
                INSERT INTO instances (
                    id, org_id, env_id, cell_id, node_id, image_ref, command,
                    cpu_millis, memory_mb, pids_limit
                ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10)
                RETURNING *
                """,
                instance_id,
                ctx.org_id,
                payload.environment_id,
                env["cell_id"],
                payload.node_id,
                payload.image_ref,
                json.dumps(payload.command),
                payload.cpu_millis,
                payload.memory_mb,
                payload.pids_limit,
            )
            assert row is not None
            await audit.record(
                conn,
                org_id=ctx.org_id,
                actor_user_id=ctx.user_id,
                action="instance.create",
                target_type="instance",
                target_id=instance_id,
                metadata={"node_id": str(payload.node_id)},
                source_ip=_client_ip(request),
            )
    except asyncpg.PostgresError as exc:
        raise map_pg_error(exc) from exc
    return InstanceOut.model_validate(dict(row))


@router.get("/instances/{instance_id}", response_model=InstanceOut)
async def get_instance(
    instance_id: UUID,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> InstanceOut:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        row = await conn.fetchrow("SELECT * FROM instances WHERE id = $1", instance_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "instance introuvable")
    return InstanceOut.model_validate(dict(row))


@router.put("/instances/{instance_id}/desired", response_model=InstanceOut)
async def set_desired_state(
    instance_id: UUID,
    payload: InstanceDesiredUpdate,
    request: Request,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> InstanceOut:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        row = await conn.fetchrow(
            """
            UPDATE instances
               SET desired_state = $2,
                   generation = generation + 1,
                   updated_at = now()
             WHERE id = $1
               AND desired_state IS DISTINCT FROM $2
            RETURNING *
            """,
            instance_id,
            payload.desired_state,
        )
        if row is None:
            row = await conn.fetchrow("SELECT * FROM instances WHERE id = $1", instance_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "instance introuvable")
        await audit.record(
            conn,
            org_id=ctx.org_id,
            actor_user_id=ctx.user_id,
            action="instance.desired_state",
            target_type="instance",
            target_id=instance_id,
            metadata={"desired_state": payload.desired_state},
            source_ip=_client_ip(request),
        )
    return InstanceOut.model_validate(dict(row))


@router.get("/instances/{instance_id}/status", response_model=InstanceStatusOut)
async def get_instance_status(
    instance_id: UUID,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> InstanceStatusOut:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        row = await conn.fetchrow(
            "SELECT * FROM instance_status WHERE instance_id = $1", instance_id
        )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "statut indisponible")
    return InstanceStatusOut.model_validate(dict(row))
