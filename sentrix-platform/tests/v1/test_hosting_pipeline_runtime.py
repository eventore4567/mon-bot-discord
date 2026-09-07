from __future__ import annotations

import hashlib

import asyncpg

from libs.db import Database
from libs.ids import uuid7
from tests.conftest import Tenant

CELL_ID = "01920000-0000-7000-8000-000000000001"


async def test_build_to_healthy_instance_pipeline_is_durable(
    app_db: Database,
    admin_conn: asyncpg.Connection[asyncpg.Record],
    tenants: tuple[Tenant, Tenant],
) -> None:
    tenant, _other = tenants
    env_id = uuid7()
    node_id = uuid7()
    build_id = uuid7()
    release_id = uuid7()
    deployment_id = uuid7()
    builder_id = uuid7()
    orchestrator_id = uuid7()
    builder_token = b"builder-runtime-test-token"
    orchestrator_token = b"orchestrator-runtime-test-token"
    node_token = b"node-runtime-test-token"
    image_digest = "sha256:" + "a" * 64
    image_ref = f"registry.invalid/sentrix/test@{image_digest}"

    await admin_conn.execute(
        "UPDATE projects SET repo_full_name = 'eventore4567/mon-bot-discord' WHERE id = $1",
        tenant.project_id,
    )
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
        f"pipeline-node-{node_id}",
        hashlib.sha256(node_token).digest(),
    )
    await admin_conn.execute(
        """
        INSERT INTO control_workers (id, kind, name, token_sha256)
        VALUES
            ($1, 'builder', $2, $3),
            ($4, 'orchestrator', $5, $6)
        """,
        builder_id,
        f"builder-{builder_id}",
        hashlib.sha256(builder_token).digest(),
        orchestrator_id,
        f"orchestrator-{orchestrator_id}",
        hashlib.sha256(orchestrator_token).digest(),
    )

    try:
        async with app_db.tenant_tx(tenant.org_id) as conn:
            await conn.execute(
                """
                INSERT INTO builds (
                    id, org_id, environment_id, commit_sha, cache_key, status
                ) VALUES ($1, $2, $3, $4, $5, 'queued')
                """,
                build_id,
                tenant.org_id,
                env_id,
                "b" * 40,
                "c" * 64,
            )

        queued = await admin_conn.fetchrow(
            "SELECT status FROM build_control_queue WHERE build_id = $1",
            build_id,
        )
        assert queued is not None and queued["status"] == "queued"

        async with app_db.admin_tx() as conn:
            claimed = await conn.fetchrow(
                "SELECT * FROM public.sentrix_builder_claim($1,$2,$3)",
                builder_id,
                hashlib.sha256(builder_token).digest(),
                300,
            )
        assert claimed is not None
        assert claimed["build_id"] == build_id
        assert claimed["repository"] == "eventore4567/mon-bot-discord"
        assert claimed["lease_attempt"] == 1

        async with app_db.admin_tx() as conn:
            renewed = await conn.fetchval(
                "SELECT public.sentrix_builder_renew($1,$2,$3,$4,$5)",
                builder_id,
                hashlib.sha256(builder_token).digest(),
                build_id,
                1,
                300,
            )
        assert renewed is True

        async with app_db.admin_tx() as conn:
            published = await conn.fetchrow(
                """
                SELECT * FROM public.sentrix_builder_report(
                    $1,$2,$3,$4,'succeeded',$5,$6,NULL,$7,$8
                )
                """,
                builder_id,
                hashlib.sha256(builder_token).digest(),
                build_id,
                1,
                image_ref,
                image_digest,
                release_id,
                deployment_id,
            )
        assert published is not None
        assert published["release_id"] == release_id
        assert published["deployment_id"] == deployment_id

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

        first = await tick()
        second = await tick()
        third = await tick()
        assert first["deployment_step"] == "prewarm"
        assert second["deployment_step"] == "handover"
        assert third["deployment_step"] == "health"

        async with app_db.tenant_tx(tenant.org_id) as conn:
            instance = await conn.fetchrow(
                """
                SELECT id, node_id, image_ref, generation
                FROM instances WHERE env_id = $1
                """,
                env_id,
            )
        assert instance is not None
        assert instance["node_id"] == node_id
        assert instance["image_ref"] == image_ref
        assert instance["generation"] == 1

        async with app_db.admin_tx() as conn:
            changed = await conn.fetchval(
                """
                SELECT public.sentrix_agent_report_instance(
                    $1,$2,$3,'running',$4,$5,0,'healthy','pipeline test'
                )
                """,
                node_id,
                hashlib.sha256(node_token).digest(),
                instance["id"],
                "container-runtime-test",
                instance["generation"],
            )
        assert changed is True

        final = await tick()
        assert final["deployment_status"] == "succeeded"
        assert final["deployment_step"] == "done"

        async with app_db.tenant_tx(tenant.org_id) as conn:
            deployment = await conn.fetchrow(
                """
                SELECT status, active_release_id, target_generation
                FROM deployments WHERE id = $1
                """,
                deployment_id,
            )
            build = await conn.fetchrow(
                "SELECT status, image_digest FROM builds WHERE id = $1",
                build_id,
            )
        assert deployment is not None
        assert deployment["status"] == "succeeded"
        assert deployment["active_release_id"] == release_id
        assert deployment["target_generation"] == 1
        assert build is not None
        assert build["status"] == "succeeded"
        assert build["image_digest"] == image_digest
    finally:
        await admin_conn.execute("DELETE FROM deployments WHERE id = $1", deployment_id)
        await admin_conn.execute("DELETE FROM releases WHERE id = $1", release_id)
        await admin_conn.execute("DELETE FROM builds WHERE id = $1", build_id)
        await admin_conn.execute("DELETE FROM instances WHERE env_id = $1", env_id)
        await admin_conn.execute("DELETE FROM environments WHERE id = $1", env_id)
        await admin_conn.execute("DELETE FROM nodes WHERE id = $1", node_id)
        await admin_conn.execute(
            "DELETE FROM control_workers WHERE id = ANY($1::uuid[])",
            [builder_id, orchestrator_id],
        )
        await admin_conn.execute(
            "UPDATE projects SET repo_full_name = NULL WHERE id = $1",
            tenant.project_id,
        )
