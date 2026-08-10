"""Routes CRUD tenant : projets, bots, environnements.

Toutes les requetes passent par db.tenant_tx(org_id). Aucune route ne pose
elle-meme le contexte tenant, et aucune ne filtre manuellement par org_id dans
son SQL : c'est RLS qui s'en charge. Les clauses WHERE ne portent donc que sur
l'identifiant de la ressource.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status

from libs import audit
from libs.ids import uuid7
from libs.models import (
    BotCreate,
    BotOut,
    EnvironmentCreate,
    EnvironmentOut,
    ProjectCreate,
    ProjectOut,
)
from services.api.deps import AppState, OrgContext, get_state, map_pg_error, require_org

router = APIRouter(prefix="/v1/orgs/{org_id}", tags=["resources"])

DEFAULT_CELL = UUID("01920000-0000-7000-8000-000000000001")


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# --------------------------------------------------------------------------- projets


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


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: UUID,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> ProjectOut:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        # Pas de filtre org_id : RLS s'en charge. Une ressource d'une autre org
        # est simplement invisible -> 404, jamais 403.
        row = await conn.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)

    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ressource introuvable")
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
    return [ProjectOut.model_validate(dict(r)) for r in rows]


# ------------------------------------------------------------------------------ bots


@router.post("/bots", response_model=BotOut, status_code=status.HTTP_201_CREATED)
async def create_bot(
    payload: BotCreate,
    request: Request,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> BotOut:
    """Creation d'un bot.

    Si project_id appartient a une autre org, la FK composite
    (project_id, org_id) -> projects(id, org_id) leve 23503, traduit en 404.
    Le rejet vient de PostgreSQL, pas d'une verification applicative.
    """
    bot_id = uuid7()
    try:
        async with state.db.tenant_tx(ctx.org_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO bots (id, org_id, project_id, name, library)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
                """,
                bot_id,
                ctx.org_id,
                payload.project_id,
                payload.name,
                payload.library,
            )
            assert row is not None
            await audit.record(
                conn,
                org_id=ctx.org_id,
                actor_user_id=ctx.user_id,
                action="bot.create",
                target_type="bot",
                target_id=bot_id,
                metadata={"name": payload.name, "library": payload.library},
                source_ip=_client_ip(request),
            )
    except asyncpg.PostgresError as exc:
        raise map_pg_error(exc) from exc

    return BotOut.model_validate(dict(row))


@router.get("/bots/{bot_id}", response_model=BotOut)
async def get_bot(
    bot_id: UUID,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> BotOut:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        row = await conn.fetchrow("SELECT * FROM bots WHERE id = $1", bot_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ressource introuvable")
    return BotOut.model_validate(dict(row))


# ---------------------------------------------------------------------- environnements


@router.post(
    "/environments", response_model=EnvironmentOut, status_code=status.HTTP_201_CREATED
)
async def create_environment(
    payload: EnvironmentCreate,
    request: Request,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> EnvironmentOut:
    """Creation d'un environnement.

    Une declaration NON VERIFIEE de discord_application_id ne reserve pas l'ID
    globalement : sinon un tenant pourrait squatter l'application publique d'un
    tiers. L'unicite cross-tenant s'active seulement quand la propriete a ete
    verifiee et que discord_application_verified_at est renseigne (P3).
    """
    env_id = uuid7()
    try:
        async with state.db.tenant_tx(ctx.org_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO environments
                    (id, org_id, bot_id, kind, discord_application_id,
                     cell_id, runtime_mode, secret_provider)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING *
                """,
                env_id,
                ctx.org_id,
                payload.bot_id,
                payload.kind,
                payload.discord_application_id,
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
                target_id=env_id,
                metadata={"kind": payload.kind, "runtime_mode": payload.runtime_mode},
                source_ip=_client_ip(request),
            )
    except asyncpg.PostgresError as exc:
        raise map_pg_error(exc) from exc

    return EnvironmentOut.model_validate(dict(row))


@router.get("/environments/{environment_id}", response_model=EnvironmentOut)
async def get_environment(
    environment_id: UUID,
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> EnvironmentOut:
    async with state.db.tenant_tx(ctx.org_id) as conn:
        row = await conn.fetchrow("SELECT * FROM environments WHERE id = $1", environment_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ressource introuvable")
    return EnvironmentOut.model_validate(dict(row))
