"""Fixtures de test.

PostgreSQL REEL obligatoire : RLS et FK composites ne peuvent pas etre testes
sur SQLite. Deux modes :
  - TEST_DATABASE_URL defini  -> utilise ce cluster (dev local, CI avec service)
  - sinon                     -> testcontainers demarre un PostgreSQL jetable
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio

from libs.db import Database
from libs.db.migrator import apply_all
from libs.ids import uuid7

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
BOOTSTRAP_ROLES = Path(__file__).resolve().parent.parent / "ops" / "bootstrap" / "roles.sql"


@pytest.fixture(scope="session")
def superuser_dsn() -> Iterator[str]:
    """DSN superutilisateur : cree les roles et applique les migrations."""
    dsn = os.environ.get("TEST_DATABASE_URL")
    if dsn:
        yield dsn
        return

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")


# loop_scope="session" est OBLIGATOIRE : sans lui, pytest-asyncio (>= 0.24)
# execute une fixture async de portee session sur une boucle de portee fonction,
# ce qui produit un ScopeMismatch ou une boucle deja fermee.
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def prepared_db(superuser_dsn: str) -> AsyncIterator[str]:
    """Roles crees, migrations appliquees. Retourne le DSN superutilisateur.

    Aucune connexion vivante ne franchit la frontiere de portee : la fonction
    rend une simple chaine, la connexion est fermee avant. Les fixtures de
    portee fonction peuvent donc en dependre sans conflit de boucle.
    """
    conn = await asyncpg.connect(superuser_dsn)
    try:
        await conn.execute(BOOTSTRAP_ROLES.read_text(encoding="utf-8"))
        await apply_all(conn, MIGRATIONS_DIR)
        # Les migrations tournent ici en superutilisateur ; on transfere la
        # propriete au migrator pour refleter la production (et prouver que
        # FORCE ROW LEVEL SECURITY s'applique bien au proprietaire).
        for table in (
            "organizations",
            "users",
            "org_members",
            "projects",
            "bots",
            "environments",
            "audit_log",
            "cells",
            "schema_migrations",
            "nodes",
            "instances",
            "agent_desired_state",
            "instance_status",
            "webhook_deliveries",
            "builds",
            "releases",
            "identify_budgets",
            "identify_reservations",
            "identify_breakers",
            "deployments",
            "deployment_leases",
            "deployment_attempts",
            "deployment_effects",
            "environment_secrets",
            "usage_samples",
            "log_quota_state",
            "promotion_gates",
        ):
            await conn.execute(f"ALTER TABLE {table} OWNER TO sentrix_migrator")
    finally:
        await conn.close()
    yield superuser_dsn


def _app_dsn(superuser_dsn: str) -> str:
    """Meme cluster/base, mais avec le role applicatif (sans BYPASSRLS).

    C'est ce qui rend la suite d'attaques credible : elle s'execute avec le role
    reellement utilise en production, pas avec un superutilisateur qui
    contournerait RLS sans rien prouver.
    """
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(superuser_dsn)
    host = parsed.hostname or "localhost"
    netloc = f"sentrix_app:app_dev_only@{host}"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


@pytest_asyncio.fixture
async def app_db(prepared_db: str) -> AsyncIterator[Database]:
    """Pool connecte en tant que sentrix_app."""
    database = Database(_app_dsn(prepared_db))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest_asyncio.fixture
async def admin_conn(prepared_db: str) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
    """Connexion superutilisateur : sert a monter le decor, jamais a tester."""
    conn = await asyncpg.connect(prepared_db)
    try:
        yield conn
    finally:
        await conn.close()


class Tenant:
    """Decor d'un tenant : org, utilisateur, projet, bot, environnement."""

    def __init__(self, org_id: UUID, user_id: UUID, project_id: UUID, bot_id: UUID) -> None:
        self.org_id = org_id
        self.user_id = user_id
        self.project_id = project_id
        self.bot_id = bot_id


async def _make_tenant(conn: asyncpg.Connection[asyncpg.Record], slug: str) -> Tenant:
    org_id, user_id, project_id, bot_id = uuid7(), uuid7(), uuid7(), uuid7()
    await conn.execute(
        "INSERT INTO organizations (id, name, slug) VALUES ($1, $2, $3)",
        org_id,
        f"Org {slug}",
        slug,
    )
    await conn.execute(
        "INSERT INTO users (id, discord_user_id, display_name) VALUES ($1, $2, $3)",
        user_id,
        f"discord-{slug}",
        f"User {slug}",
    )
    await conn.execute(
        "INSERT INTO org_members (org_id, user_id, role) VALUES ($1, $2, 'owner')",
        org_id,
        user_id,
    )
    await conn.execute(
        "INSERT INTO projects (id, org_id, name) VALUES ($1, $2, $3)",
        project_id,
        org_id,
        f"projet-{slug}",
    )
    await conn.execute(
        "INSERT INTO bots (id, org_id, project_id, name) VALUES ($1, $2, $3, $4)",
        bot_id,
        org_id,
        project_id,
        f"bot-{slug}",
    )
    return Tenant(org_id, user_id, project_id, bot_id)


@pytest_asyncio.fixture
async def tenants(
    admin_conn: asyncpg.Connection[asyncpg.Record],
) -> AsyncIterator[tuple[Tenant, Tenant]]:
    """Deux tenants isoles, A et B, avec nettoyage complet apres le test."""
    suffix = uuid7().hex[:8]
    a = await _make_tenant(admin_conn, f"a-{suffix}")
    b = await _make_tenant(admin_conn, f"b-{suffix}")
    try:
        yield a, b
    finally:
        for tenant in (a, b):
            await admin_conn.execute("DELETE FROM instance_status WHERE org_id = $1", tenant.org_id)
            await admin_conn.execute("DELETE FROM instances WHERE org_id = $1", tenant.org_id)
            await admin_conn.execute("DELETE FROM audit_log WHERE org_id = $1", tenant.org_id)
            await admin_conn.execute("DELETE FROM environments WHERE org_id = $1", tenant.org_id)
            await admin_conn.execute("DELETE FROM bots WHERE org_id = $1", tenant.org_id)
            await admin_conn.execute("DELETE FROM projects WHERE org_id = $1", tenant.org_id)
            await admin_conn.execute("DELETE FROM org_members WHERE org_id = $1", tenant.org_id)
            await admin_conn.execute("DELETE FROM users WHERE id = $1", tenant.user_id)
            await admin_conn.execute("DELETE FROM organizations WHERE id = $1", tenant.org_id)
