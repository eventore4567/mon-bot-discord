"""Production bootstrap for the SentriX Hosting control plane.

The Railway PostgreSQL superuser is used only during bootstrap to create a
logical database and least-privilege roles. Uvicorn is then exec'd with only the
`sentrix_app` DSN in its environment, so the long-lived API cannot use bootstrap
or migration credentials.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import asyncpg

from libs.db.migrator import apply_all

_PLATFORM_DB_DEFAULT = "sentrix_platform"
_DB_NAME = re.compile(r"^[a-z][a-z0-9_]{2,47}$")
_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class BootstrapError(RuntimeError):
    """A production bootstrap invariant could not be established."""


def _database_name() -> str:
    name = os.environ.get("SENTRIX_PLATFORM_DB_NAME", _PLATFORM_DB_DEFAULT).strip()
    if not _DB_NAME.fullmatch(name):
        raise BootstrapError("SENTRIX_PLATFORM_DB_NAME invalide")
    return name


def database_dsn(source: str, *, database: str) -> str:
    """Switch only the logical database while preserving Railway credentials verbatim."""
    parsed = urlsplit(source)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise BootstrapError("POSTGRES_SUPERUSER_URL doit etre une URL PostgreSQL absolue")
    return urlunsplit(
        (parsed.scheme, parsed.netloc, f"/{quote(database, safe='')}", parsed.query, "")
    )


def role_dsn(source: str, *, username: str, password: str, database: str) -> str:
    """Return a DSN with a fixed role and logical database, preserving TLS/query options."""
    parsed = urlsplit(source)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise BootstrapError("POSTGRES_SUPERUSER_URL doit etre une URL PostgreSQL absolue")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{host}{port}"
    return urlunsplit((parsed.scheme, netloc, f"/{quote(database, safe='')}", parsed.query, ""))


async def _safe_role_password_sql(
    conn: asyncpg.Connection[asyncpg.Record], role: str, password: str
) -> str:
    sql = await conn.fetchval(
        "SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', $1::text, $2::text)",
        role,
        password,
    )
    if not isinstance(sql, str):
        raise BootstrapError("impossible de preparer le mot de passe PostgreSQL")
    return sql


async def _safe_database_ddl(
    conn: asyncpg.Connection[asyncpg.Record], database: str, *, exists: bool
) -> str:
    template = (
        "ALTER DATABASE %I OWNER TO sentrix_migrator"
        if exists
        else "CREATE DATABASE %I OWNER sentrix_migrator"
    )
    sql = await conn.fetchval("SELECT format($1::text, $2::text)", template, database)
    if not isinstance(sql, str):
        raise BootstrapError("impossible de preparer le DDL PostgreSQL")
    return sql


async def _ensure_roles(
    conn: asyncpg.Connection[asyncpg.Record], *, app_password: str, migrator_password: str
) -> None:
    await conn.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sentrix_migrator') THEN
                CREATE ROLE sentrix_migrator LOGIN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sentrix_app') THEN
                CREATE ROLE sentrix_app LOGIN;
            END IF;
        END
        $$;
        """
    )
    await conn.execute(await _safe_role_password_sql(conn, "sentrix_migrator", migrator_password))
    await conn.execute(await _safe_role_password_sql(conn, "sentrix_app", app_password))
    await conn.execute(
        "ALTER ROLE sentrix_migrator NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
    )
    await conn.execute(
        "ALTER ROLE sentrix_app NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
    )
    await conn.execute("REVOKE sentrix_migrator FROM sentrix_app")


async def _ensure_database(conn: asyncpg.Connection[asyncpg.Record], database: str) -> None:
    exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", database)
    await conn.execute(await _safe_database_ddl(conn, database, exists=exists is not None))


async def bootstrap() -> str:
    superuser_url = os.environ.get("POSTGRES_SUPERUSER_URL", "").strip()
    app_password = os.environ.get("SENTRIX_APP_DB_PASSWORD", "")
    migrator_password = os.environ.get("SENTRIX_MIGRATOR_DB_PASSWORD", "")
    if not superuser_url:
        raise BootstrapError("POSTGRES_SUPERUSER_URL absente")
    if len(app_password) < 32 or len(migrator_password) < 32:
        raise BootstrapError("mots de passe DB Hosting trop courts")
    if app_password == migrator_password:
        raise BootstrapError("les roles app et migrator doivent avoir des secrets distincts")

    database = _database_name()

    admin = await asyncpg.connect(superuser_url)
    try:
        await _ensure_roles(
            admin,
            app_password=app_password,
            migrator_password=migrator_password,
        )
        await _ensure_database(admin, database)
    finally:
        await admin.close()

    platform_admin = await asyncpg.connect(database_dsn(superuser_url, database=database))
    try:
        await platform_admin.execute("GRANT CREATE, USAGE ON SCHEMA public TO sentrix_migrator")
        await platform_admin.execute("GRANT USAGE ON SCHEMA public TO sentrix_app")
    finally:
        await platform_admin.close()

    migrator_dsn = role_dsn(
        superuser_url,
        username="sentrix_migrator",
        password=migrator_password,
        database=database,
    )
    migrator = await asyncpg.connect(migrator_dsn)
    try:
        await apply_all(migrator, _MIGRATIONS_DIR)
    finally:
        await migrator.close()

    app_dsn = role_dsn(
        superuser_url,
        username="sentrix_app",
        password=app_password,
        database=database,
    )
    verifier = await asyncpg.connect(app_dsn)
    try:
        row = await verifier.fetchrow(
            "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        if row is None or row["rolname"] != "sentrix_app":
            raise BootstrapError("role applicatif inattendu")
        if bool(row["rolsuper"]) or bool(row["rolbypassrls"]):
            raise BootstrapError("sentrix_app ne doit jamais etre superuser/BYPASSRLS")
        await verifier.fetchval("SELECT count(*) FROM cells")
    finally:
        await verifier.close()

    return app_dsn


def main() -> None:
    app_dsn = asyncio.run(bootstrap())
    os.environ["DATABASE_URL"] = app_dsn
    for name in (
        "POSTGRES_SUPERUSER_URL",
        "SENTRIX_MIGRATOR_DB_PASSWORD",
        "SENTRIX_APP_DB_PASSWORD",
        "MIGRATIONS_DATABASE_URL",
    ):
        os.environ.pop(name, None)
    port = os.environ.get("PORT", "8080")
    # Intentional exec: replace the bootstrap process so privileged DB secrets
    # cannot remain reachable by the long-lived API process.
    os.execv(  # noqa: S606
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "services.api.main:app",
            "--host",
            "0.0.0.0",  # noqa: S104 - Railway container must listen on all interfaces.
            "--port",
            port,
            "--proxy-headers",
        ],
    )


if __name__ == "__main__":
    main()
