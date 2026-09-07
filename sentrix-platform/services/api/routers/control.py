"""Private API used by SentriX builder and orchestrator workers.

Workers never receive broad PostgreSQL privileges. They authenticate with a
machine UUID + token and call SECURITY DEFINER functions that expose only the
single build/deployment they currently own.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from libs.ids import uuid7
from services.api.deps import AppState, get_state

router = APIRouter(prefix="/v1/control", tags=["control-workers"])


def _token_digest(raw: str) -> bytes:
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _worker_headers(
    worker_id: Annotated[UUID, Header(alias="X-Sentrix-Worker-Id")],
    worker_token: Annotated[
        str,
        Header(alias="X-Sentrix-Worker-Token", min_length=24, max_length=512),
    ],
) -> tuple[UUID, bytes]:
    return worker_id, _token_digest(worker_token)


def _map_worker_error(exc: asyncpg.PostgresError) -> HTTPException:
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate == "42501":
        return HTTPException(status.HTTP_401_UNAUTHORIZED, "worker non autorise")
    if sqlstate == "22023":
        return HTTPException(status.HTTP_400_BAD_REQUEST, "requete worker invalide")
    return HTTPException(status.HTTP_409_CONFLICT, "operation worker impossible")


class BuildJob(BaseModel):
    build_id: UUID
    org_id: UUID
    environment_id: UUID
    repository: str
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    library: str
    runtime_mode: str
    lease_attempt: int = Field(ge=1)


class BuildLease(BaseModel):
    build_id: UUID
    lease_attempt: int = Field(ge=1)


class BuildReport(BaseModel):
    build_id: UUID
    lease_attempt: int = Field(ge=1)
    outcome: Literal["succeeded", "rejected", "failed"]
    image_ref: str | None = Field(default=None, max_length=768)
    image_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    error: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_success_payload(self) -> BuildReport:
        if self.outcome == "succeeded" and (self.image_ref is None or self.image_digest is None):
            raise ValueError("successful build requires immutable image reference")
        return self


class BuildReportOut(BaseModel):
    release_id: UUID | None = None
    deployment_id: UUID | None = None
    final_status: str


class OrchestratorTickOut(BaseModel):
    deployment_id: UUID
    deployment_status: str
    deployment_step: str
    detail: str


@router.post("/builder/claim", response_model=BuildJob | None)
async def claim_build(
    auth: Annotated[tuple[UUID, bytes], Depends(_worker_headers)],
    state: Annotated[AppState, Depends(get_state)],
) -> BuildJob | None:
    worker_id, digest = auth
    try:
        async with state.db.admin_tx() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM public.sentrix_builder_claim($1, $2, $3)",
                worker_id,
                digest,
                300,
            )
    except asyncpg.PostgresError as exc:
        raise _map_worker_error(exc) from exc
    if row is None:
        return None
    return BuildJob.model_validate(dict(row))


@router.post("/builder/renew", status_code=status.HTTP_204_NO_CONTENT)
async def renew_build(
    payload: BuildLease,
    auth: Annotated[tuple[UUID, bytes], Depends(_worker_headers)],
    state: Annotated[AppState, Depends(get_state)],
) -> None:
    worker_id, digest = auth
    try:
        async with state.db.admin_tx() as conn:
            await conn.fetchval(
                "SELECT public.sentrix_builder_renew($1,$2,$3,$4,$5)",
                worker_id,
                digest,
                payload.build_id,
                payload.lease_attempt,
                300,
            )
    except asyncpg.PostgresError as exc:
        raise _map_worker_error(exc) from exc


@router.post("/builder/report", response_model=BuildReportOut)
async def report_build(
    payload: BuildReport,
    auth: Annotated[tuple[UUID, bytes], Depends(_worker_headers)],
    state: Annotated[AppState, Depends(get_state)],
) -> BuildReportOut:
    worker_id, digest = auth
    try:
        async with state.db.admin_tx() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM public.sentrix_builder_report(
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10
                )
                """,
                worker_id,
                digest,
                payload.build_id,
                payload.lease_attempt,
                payload.outcome,
                payload.image_ref,
                payload.image_digest,
                payload.error,
                uuid7(),
                uuid7(),
            )
    except asyncpg.PostgresError as exc:
        raise _map_worker_error(exc) from exc
    assert row is not None
    return BuildReportOut.model_validate(dict(row))


@router.post("/orchestrator/tick", response_model=OrchestratorTickOut | None)
async def orchestrator_tick(
    auth: Annotated[tuple[UUID, bytes], Depends(_worker_headers)],
    state: Annotated[AppState, Depends(get_state)],
) -> OrchestratorTickOut | None:
    worker_id, digest = auth
    try:
        async with state.db.admin_tx() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM public.sentrix_orchestrator_tick($1,$2,$3,$4,$5,$6)",
                worker_id,
                digest,
                uuid7(),
                uuid7(),
                30,
                90,
            )
    except asyncpg.PostgresError as exc:
        raise _map_worker_error(exc) from exc
    if row is None:
        return None
    return OrchestratorTickOut.model_validate(dict(row))
