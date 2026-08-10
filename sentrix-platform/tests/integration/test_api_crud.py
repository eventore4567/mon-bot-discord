"""CRUD via l'API + verification que toute mutation ecrit un audit_log."""

from __future__ import annotations

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from libs.db import Database
from services.api.auth import SessionCodec
from services.api.main import create_app
from tests.conftest import Tenant

pytestmark = pytest.mark.asyncio

SESSION_SECRET = b"y" * 48


@pytest.fixture
def client_factory(app_db: Database):  # type: ignore[no-untyped-def]
    codec = SessionCodec(SESSION_SECRET)
    app = create_app(db=app_db, sessions=codec)

    def make(user_id):  # type: ignore[no-untyped-def]
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {codec.issue(user_id)}"},
        )

    return make


async def test_full_crud_flow(
    tenants: tuple[Tenant, Tenant],
    client_factory,  # type: ignore[no-untyped-def]
) -> None:
    a, _ = tenants
    async with client_factory(a.user_id) as client:
        created = await client.post(
            f"/v1/orgs/{a.org_id}/projects",
            json={"name": "mon-bot-discord", "default_branch": "main"},
        )
        assert created.status_code == 201
        project_id = created.json()["id"]

        fetched = await client.get(f"/v1/orgs/{a.org_id}/projects/{project_id}")
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "mon-bot-discord"

        bot = await client.post(
            f"/v1/orgs/{a.org_id}/bots",
            json={"project_id": project_id, "name": "sentrix", "library": "discordpy"},
        )
        assert bot.status_code == 201
        bot_id = bot.json()["id"]

        env = await client.post(
            f"/v1/orgs/{a.org_id}/environments",
            json={
                "bot_id": bot_id,
                "kind": "prod",
                "runtime_mode": "generic",
                "secret_provider": "env",
            },
        )
        assert env.status_code == 201
        body = env.json()
        assert body["cell_id"] is not None
        assert body["discord_application_verified_at"] is None


async def test_every_mutation_writes_audit_log(
    tenants: tuple[Tenant, Tenant],
    client_factory,  # type: ignore[no-untyped-def]
    admin_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    a, _ = tenants
    async with client_factory(a.user_id) as client:
        project = await client.post(f"/v1/orgs/{a.org_id}/projects", json={"name": "audite"})
        project_id = project.json()["id"]
        bot = await client.post(
            f"/v1/orgs/{a.org_id}/bots", json={"project_id": project_id, "name": "b"}
        )
        bot_id = bot.json()["id"]
        await client.post(
            f"/v1/orgs/{a.org_id}/environments", json={"bot_id": bot_id, "kind": "prod"}
        )

    rows = await admin_conn.fetch(
        "SELECT action, target_type, target_id, actor_user_id FROM audit_log WHERE org_id = $1",
        a.org_id,
    )
    actions = {r["action"] for r in rows}
    assert {"project.create", "bot.create", "environment.create"} <= actions
    assert all(r["actor_user_id"] == a.user_id for r in rows)


async def test_failed_mutation_leaves_no_audit_entry(
    tenants: tuple[Tenant, Tenant],
    client_factory,  # type: ignore[no-untyped-def]
    admin_conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    """Une mutation annulee n'ecrit pas d'audit : meme transaction, meme sort."""
    a, b = tenants
    before = await admin_conn.fetchval("SELECT count(*) FROM audit_log WHERE org_id = $1", a.org_id)

    async with client_factory(a.user_id) as client:
        response = await client.post(
            f"/v1/orgs/{a.org_id}/bots",
            json={"project_id": str(b.project_id), "name": "echec"},
        )
        assert response.status_code == 404

    after = await admin_conn.fetchval("SELECT count(*) FROM audit_log WHERE org_id = $1", a.org_id)
    assert after == before


async def test_unauthenticated_request_rejected(app_db: Database) -> None:
    app = create_app(db=app_db, sessions=SessionCodec(SESSION_SECRET))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/orgs/01920000-0000-7000-8000-000000000001/projects")
        assert response.status_code == 401


async def test_tampered_session_rejected(tenants: tuple[Tenant, Tenant], app_db: Database) -> None:
    a, _ = tenants
    codec = SessionCodec(SESSION_SECRET)
    app = create_app(db=app_db, sessions=codec)
    forged = codec.issue(a.user_id)[:-4] + "AAAA"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {forged}"},
    ) as client:
        response = await client.get(f"/v1/orgs/{a.org_id}/projects")
        assert response.status_code == 401
