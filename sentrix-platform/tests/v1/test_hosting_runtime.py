from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import asyncpg
from fastapi import Request

from libs.db import Database
from libs.ids import uuid7
from services.api.deps import AppState, OrgContext
from services.api.routers.hosting import RuntimeAction, runtime_action
from tests.conftest import Tenant

CELL_ID = "01920000-0000-7000-8000-000000000001"


async def test_runtime_start_stop_are_idempotent_and_restart_bumps_generation(
    app_db: Database,
    admin_conn: asyncpg.Connection[asyncpg.Record],
    tenants: tuple[Tenant, Tenant],
) -> None:
    tenant, _other = tenants
    env_id = uuid7()
    node_id = uuid7()
    instance_id = uuid7()

    await admin_conn.execute(
        """
        INSERT INTO environments (id, org_id, bot_id, kind, cell_id)
        VALUES ($1, $2, $3, 'prod', $4)
        """,
        env_id,
        tenant.org_id,
        tenant.bot_id,
        CELL_ID,
    )
    await admin_conn.execute(
        """
        INSERT INTO nodes (id, cell_id, name, agent_token_sha256)
        VALUES ($1, $2, $3, decode($4, 'hex'))
        """,
        node_id,
        CELL_ID,
        f"hosting-test-{node_id}",
        "11" * 32,
    )
    await admin_conn.execute(
        """
        INSERT INTO instances (
            id, org_id, env_id, cell_id, node_id, desired_state, image_ref, generation
        ) VALUES ($1, $2, $3, $4, $5, 'running', 'example.invalid/sentrix:test', 1)
        """,
        instance_id,
        tenant.org_id,
        env_id,
        CELL_ID,
        node_id,
    )

    state = cast(AppState, SimpleNamespace(db=app_db))
    ctx = OrgContext(org_id=tenant.org_id, user_id=tenant.user_id, role="owner")
    request = Request({"type": "http", "client": ("127.0.0.1", 12345)})

    try:
        first_start = await runtime_action(env_id, RuntimeAction(action="start"), request, ctx, state)
        assert first_start.affected_instances == 0

        stopped = await runtime_action(env_id, RuntimeAction(action="stop"), request, ctx, state)
        assert stopped.affected_instances == 1
        stopped_again = await runtime_action(
            env_id, RuntimeAction(action="stop"), request, ctx, state
        )
        assert stopped_again.affected_instances == 0

        started = await runtime_action(env_id, RuntimeAction(action="start"), request, ctx, state)
        assert started.affected_instances == 1
        started_again = await runtime_action(
            env_id, RuntimeAction(action="start"), request, ctx, state
        )
        assert started_again.affected_instances == 0

        async with app_db.tenant_tx(tenant.org_id) as conn:
            before_restart = await conn.fetchrow(
                "SELECT desired_state, generation FROM instances WHERE id = $1",
                instance_id,
            )
        assert before_restart is not None
        assert before_restart["desired_state"] == "running"
        assert before_restart["generation"] == 1

        restarted = await runtime_action(
            env_id, RuntimeAction(action="restart"), request, ctx, state
        )
        assert restarted.affected_instances == 1
        restarted_again = await runtime_action(
            env_id, RuntimeAction(action="restart"), request, ctx, state
        )
        assert restarted_again.affected_instances == 1

        async with app_db.tenant_tx(tenant.org_id) as conn:
            after_restart = await conn.fetchrow(
                "SELECT desired_state, generation FROM instances WHERE id = $1",
                instance_id,
            )
        assert after_restart is not None
        assert after_restart["desired_state"] == "running"
        assert after_restart["generation"] == 3

        mirrored_admin = await admin_conn.fetchrow(
            "SELECT desired_state, generation FROM agent_desired_state WHERE instance_id = $1",
            instance_id,
        )
        assert mirrored_admin is not None
        assert mirrored_admin["desired_state"] == "running"
        assert mirrored_admin["generation"] == 3
    finally:
        await admin_conn.execute("DELETE FROM instances WHERE id = $1", instance_id)
        await admin_conn.execute("DELETE FROM environments WHERE id = $1", env_id)
        await admin_conn.execute("DELETE FROM nodes WHERE id = $1", node_id)
