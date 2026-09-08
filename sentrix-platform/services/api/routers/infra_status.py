"""Read-only infrastructure status for the authenticated Hosting dashboard.

This endpoint exposes only aggregate worker readiness. It never returns node
identifiers, agent tokens, secrets, tenant resources or private topology.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from services.api.deps import AppState, CurrentUser, get_state, require_user

router = APIRouter(prefix="/v1/infra", tags=["infra"])


class InfraStatusOut(BaseModel):
    control_plane: Literal["ok"] = "ok"
    configured_nodes: int
    online_nodes: int
    hosting_ready: bool
    mode: Literal["gvisor-worker"] = "gvisor-worker"


@router.get("/status", response_model=InfraStatusOut)
async def infra_status(
    _user: Annotated[CurrentUser, Depends(require_user)],
    state: Annotated[AppState, Depends(get_state)],
) -> InfraStatusOut:
    """Return aggregate execution-plane readiness for the dashboard."""
    async with state.db.admin_tx() as conn:
        configured = int(
            await conn.fetchval("SELECT public.sentrix_configured_worker_count()") or 0
        )

    online = await state.status_store.count_online_heartbeats()
    online = min(online, configured) if configured > 0 else 0
    return InfraStatusOut(
        configured_nodes=configured,
        online_nodes=online,
        hosting_ready=online > 0,
    )
