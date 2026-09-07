"""Tenant-owned maintenance endpoints for Hosting GitHub routing."""

from __future__ import annotations

from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from services.api.deps import AppState, OrgContext, get_state, require_org

router = APIRouter(
    prefix="/v1/orgs/{org_id}/hosting/github",
    tags=["hosting-github"],
)


class GitHubRefreshOut(BaseModel):
    environments: int


@router.post("/refresh", response_model=GitHubRefreshOut)
async def refresh_github_targets(
    ctx: Annotated[OrgContext, Depends(require_org)],
    state: Annotated[AppState, Depends(get_state)],
) -> GitHubRefreshOut:
    try:
        async with state.db.tenant_tx(ctx.org_id) as conn:
            count = await conn.fetchval("SELECT public.sentrix_refresh_github_control()")
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "ce depot GitHub est deja rattache a une autre organisation",
        ) from exc
    return GitHubRefreshOut(environments=int(count or 0))
