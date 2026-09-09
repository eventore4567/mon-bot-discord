from __future__ import annotations

import hashlib
import hmac
import json

import asyncpg
from httpx import ASGITransport, AsyncClient

from libs.db import Database
from libs.ids import uuid7
from services.api.auth import SessionCodec
from services.api.main import create_app
from tests.conftest import Tenant

CELL_ID = "01920000-0000-7000-8000-000000000001"


async def test_github_push_is_hmac_verified_and_durably_deduplicated(
    app_db: Database,
    admin_conn: asyncpg.Connection[asyncpg.Record],
    tenants: tuple[Tenant, Tenant],
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    tenant, _other = tenants
    env_id = uuid7()
    repository = f"eventore4567/webhook-{env_id.hex[:12]}"
    delivery_id = f"delivery-{env_id.hex}"
    secret = b"github-webhook-runtime-test-secret"
    body = json.dumps(
        {
            "repository": {"full_name": repository},
            "after": "d" * 40,
            "ref": "refs/heads/main",
        },
        separators=(",", ":"),
    ).encode("utf-8")
    signature = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()

    await admin_conn.execute(
        "UPDATE projects SET repo_full_name = $1 WHERE id = $2",
        repository,
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

    monkeypatch.setenv("SENTRIX_GITHUB_WEBHOOK_SECRET", secret.decode("utf-8"))
    app = create_app(db=app_db, sessions=SessionCodec(b"w" * 48))
    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Delivery": delivery_id,
        "X-GitHub-Event": "push",
        "Content-Type": "application/json",
    }

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            first = await client.post("/v1/webhooks/github", content=body, headers=headers)
            assert first.status_code == 202
            assert first.json()["queued_builds"] == 1
            assert first.json()["duplicate"] is False

            second = await client.post("/v1/webhooks/github", content=body, headers=headers)
            assert second.status_code == 202
            assert second.json()["duplicate"] is True
            assert second.json()["queued_builds"] == 0

            bad_headers = dict(headers)
            bad_headers["X-Hub-Signature-256"] = "sha256=" + "0" * 64
            bad = await client.post("/v1/webhooks/github", content=body, headers=bad_headers)
            assert bad.status_code == 401

        async with app_db.tenant_tx(tenant.org_id) as conn:
            rows = await conn.fetch(
                """
                SELECT commit_sha, status, delivery_id
                FROM builds WHERE environment_id = $1
                """,
                env_id,
            )
        assert len(rows) == 1
        assert rows[0]["commit_sha"] == "d" * 40
        assert rows[0]["status"] == "queued"
        assert rows[0]["delivery_id"] == delivery_id
    finally:
        await admin_conn.execute("DELETE FROM builds WHERE environment_id = $1", env_id)
        await admin_conn.execute(
            "DELETE FROM webhook_deliveries WHERE delivery_id = $1",
            delivery_id,
        )
        await admin_conn.execute("DELETE FROM environments WHERE id = $1", env_id)
        await admin_conn.execute(
            "UPDATE projects SET repo_full_name = NULL WHERE id = $1",
            tenant.project_id,
        )
