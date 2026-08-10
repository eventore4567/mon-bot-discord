"""Point d'entree des migrations : `python -m libs.db.migrate`.

Se connecte via MIGRATIONS_DATABASE_URL (role sentrix_migrator), en connexion
DIRECTE - jamais via PgBouncer : le DDL est incompatible avec le pooling en
mode transaction.

Sortie : 0 si tout est applique ou deja a jour, 1 en cas de derive de checksum
ou d'echec SQL.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg

from libs.db.migrator import MigrationDriftError, apply_all, discover

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


async def _run() -> int:
    dsn = os.environ.get("MIGRATIONS_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        print("erreur : MIGRATIONS_DATABASE_URL (ou DATABASE_URL) absente", file=sys.stderr)
        return 1

    known = discover(MIGRATIONS_DIR)
    print(f"{len(known)} migration(s) trouvee(s) dans {MIGRATIONS_DIR}")

    conn = await asyncpg.connect(dsn)
    try:
        applied = await apply_all(conn, MIGRATIONS_DIR)
    except MigrationDriftError as exc:
        print(f"DERIVE DE CHECKSUM : {exc}", file=sys.stderr)
        return 1
    except asyncpg.PostgresError as exc:
        code = getattr(exc, "sqlstate", "?")
        print(f"echec SQL [{code}] : {exc}", file=sys.stderr)
        return 1
    finally:
        await conn.close()

    if applied:
        for version in applied:
            print(f"  applique : {version}")
    else:
        print("  deja a jour")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
