from __future__ import annotations

import hashlib
from uuid import UUID

import asyncpg
import pytest

from libs.ids import uuid7

CELL = UUID("01920000-0000-7000-8000-000000000001")


@pytest.mark.asyncio
async def test_agent_pull_requires_token_and_only_returns_assigned(
    app_db, admin_conn: asyncpg.Connection[asyncpg.Record], tenants
) -> None:
    a, b = tenants
    token_a = b"token-a-super-secret"
    token_b = b"token-b-super-secret"
    node_a, node_b = uuid7(), uuid7()
    env_a, env_b = uuid7(), uuid7()
    inst_a, inst_b = uuid7(), uuid7()
    await admin_conn.execute(
        "INSERT INTO nodes (id, cell_id, name, agent_token_sha256) VALUES ($1,$2,$3,$4),($5,$2,$6,$7)",
        node_a,
        CELL,
        f"node-a-{node_a}",
        hashlib.sha256(token_a).digest(),
        node_b,
        f"node-b-{node_b}",
        hashlib.sha256(token_b).digest(),
    )
    await admin_conn.execute(
        "INSERT INTO environments (id,org_id,bot_id,kind,cell_id) VALUES ($1,$2,$3,'prod',$4),($5,$6,$7,'prod',$4)",
        env_a,
        a.org_id,
        a.bot_id,
        CELL,
        env_b,
        b.org_id,
        b.bot_id,
    )
    await admin_conn.execute(
        "INSERT INTO instances (id,org_id,env_id,cell_id,node_id,image_ref) VALUES ($1,$2,$3,$4,$5,'img-a'),($6,$7,$8,$4,$9,'img-b')",
        inst_a,
        a.org_id,
        env_a,
        CELL,
        node_a,
        inst_b,
        b.org_id,
        env_b,
        node_b,
    )
    async with app_db.admin_tx() as conn:
        rows = await conn.fetch(
            "SELECT * FROM public.sentrix_agent_pull($1,$2)",
            node_a,
            hashlib.sha256(token_a).digest(),
        )
        assert [row["instance_id"] for row in rows] == [inst_a]
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetch(
                "SELECT * FROM public.sentrix_agent_pull($1,$2)",
                node_a,
                hashlib.sha256(token_b).digest(),
            )
