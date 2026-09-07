from __future__ import annotations

import hashlib

import asyncpg

from libs.db import Database
from libs.ids import uuid7
from tests.conftest import Tenant

CELL_ID = "01920000-0000-7000-8000-000000000001"


async def test_rollback_is_terminal_only_after_restored_generation_is_healthy(
    app_db: Database,
    admin_conn: asyncpg.Connection[asyncpg.Record],
    tenants: tuple[Tenant, Tenant],
) -> None:
    tenant, _other = tenants
    env_id = uuid7()
    node_id = uuid7()
    old_release_id = uuid7()
    new_release_id = uuid7()
    deployment_id = uuid7()
    instance_id = uuid7()
    orchestrator_id = uuid7()
    orchestrator_token = b"rollback-orchestrator-runtime-token"
    node_token = b"rollback-node-runtime-token"
    old_digest = "sha256:" + "1" * 64
    new_digest = "sha256:" + "2" * 64
    old_image = f"registry.invalid/sentrix/old@{old_digest}"
    new_image = f"registry.invalid/sentrix/new@{new_digest}"

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
        VALUES ($1, $2, $3, $4)
        """,
        node_id,
        CELL_ID,
        f"rollback-node-{node_id}",
        hashlib.sha256(node_token).digest(),
    )
    await admin_conn.execute(
        """
        INSERT INTO control_workers (id, kind, name, token_sha256)
        VALUES ($1, 'orchestrator', $2, $3)
        """,
        orchestrator_id,
        f"rollback-orchestrator-{orchestrator_id}",
        hashlib.sha256(orchestrator_token).digest(),
    )

    try:
        async with app_db.tenant_tx(tenant.org_id) as conn:
            await conn.execute(
                """
                INSERT INTO releases (
                    id, org_id, environment_id, image_digest, image_ref,
                    config_hash, secret_version, identity_key
                ) VALUES
                    ($1, $2, $3, $4, $5, $6, 0, $7),
                    ($8, $2, $3, $9, $10, $11, 0, $12)
                """,
                old_release_id,
                tenant.org_id,
                env_id,
                old_digest,
                old_image,
                "3" * 64,
                "4" * 64,
                new_release_id,
                new_digest,
                new_image,
                "5" * 64,
                "6" * 64,
            )
            await conn.execute(
                """
                INSERT INTO instances (
                    id, org_id, env_id, cell_id, node_id,
                    desired_state, image_ref, generation
                ) VALUES ($1, $2, $3, $4, $5, 'running', $6, 1)
                """,
                instance_id,
                tenant.org_id,
                env_id,
                CELL_ID,
                node_id,
                old_image,
            )
            await conn.execute(
                """
                INSERT INTO deployments (
                    id, org_id, environment_id, release_id, previous_release_id,
                    active_release_id, idempotency_key
                ) VALUES ($1, $2, $3, $4, $5, $5, $6)
                """,
                deployment_id,
                tenant.org_id,
                env_id,
                new_release_id,
                old_release_id,
                f"rollback-runtime:{deployment_id}",
            )

        async def tick() -> asyncpg.Record:
            async with app_db.admin_tx() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM public.sentrix_orchestrator_tick($1,$2,$3,$4,$5,$6)",
                    orchestrator_id,
                    hashlib.sha256(orchestrator_token).digest(),
                    uuid7(),
                    uuid7(),
                    30,
                    90,
                )
            assert row is not None
            return row

        assert (await tick())["deployment_step"] == "prewarm"
        assert (await tick())["deployment_step"] == "handover"
        assert (await tick())["deployment_step"] == "health"

        async with app_db.tenant_tx(tenant.org_id) as conn:
            instance = await conn.fetchrow(
                "SELECT image_ref, generation FROM instances WHERE id = $1",
                instance_id,
            )
        assert instance is not None
        assert instance["image_ref"] == new_image
        assert instance["generation"] == 2

        async with app_db.admin_tx() as conn:
            changed = await conn.fetchval(
                """
                SELECT public.sentrix_agent_report_instance(
                    $1,$2,$3,'failed',$4,$5,1,'unhealthy','new release failed'
                )
                """,
                node_id,
                hashlib.sha256(node_token).digest(),
                instance_id,
                "container-new-failed",
                2,
            )
        assert changed is True

        rollback_requested = await tick()
        assert rollback_requested["deployment_status"] == "running"
        assert rollback_requested["deployment_step"] == "rollback_health"

        async with app_db.tenant_tx(tenant.org_id) as conn:
            deployment = await conn.fetchrow(
                """
                SELECT status, step, active_release_id, target_generation
                FROM deployments WHERE id = $1
                """,
                deployment_id,
            )
            restored = await conn.fetchrow(
                "SELECT image_ref, generation FROM instances WHERE id = $1",
                instance_id,
            )
        assert deployment is not None
        assert deployment["status"] == "running"
        assert deployment["step"] == "rollback_health"
        assert deployment["active_release_id"] == old_release_id
        assert deployment["target_generation"] == 3
        assert restored is not None
        assert restored["image_ref"] == old_image
        assert restored["generation"] == 3

        waiting = await tick()
        assert waiting["deployment_status"] == "running"
        assert waiting["deployment_step"] == "rollback_health"

        async with app_db.admin_tx() as conn:
            changed = await conn.fetchval(
                """
                SELECT public.sentrix_agent_report_instance(
                    $1,$2,$3,'running',$4,$5,0,'healthy','rollback healthy'
                )
                """,
                node_id,
                hashlib.sha256(node_token).digest(),
                instance_id,
                "container-old-restored",
                3,
            )
        assert changed is True

        final = await tick()
        assert final["deployment_status"] == "rolled_back"
        assert final["deployment_step"] == "done"

        async with app_db.tenant_tx(tenant.org_id) as conn:
            deployment = await conn.fetchrow(
                """
                SELECT status, step, active_release_id
                FROM deployments WHERE id = $1
                """,
                deployment_id,
            )
        assert deployment is not None
        assert deployment["status"] == "rolled_back"
        assert deployment["step"] == "done"
        assert deployment["active_release_id"] == old_release_id
    finally:
        await admin_conn.execute("DELETE FROM deployments WHERE id = $1", deployment_id)
        await admin_conn.execute("DELETE FROM instances WHERE id = $1", instance_id)
        await admin_conn.execute(
            "DELETE FROM releases WHERE id = ANY($1::uuid[])",
            [old_release_id, new_release_id],
        )
        await admin_conn.execute("DELETE FROM environments WHERE id = $1", env_id)
        await admin_conn.execute("DELETE FROM nodes WHERE id = $1", node_id)
        await admin_conn.execute("DELETE FROM control_workers WHERE id = $1", orchestrator_id)
