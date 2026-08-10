"""Runner de migrations SQL numerotees, forward-only, avec checksums.

Regles :
  - Un fichier applique est IMMUABLE. Une correction = une nouvelle migration.
  - Le checksum de chaque migration deja appliquee est verifie au demarrage.
    Toute divergence bloque : c'est la protection contre la derive entre
    environnements (quelqu'un a edite une migration deja passee en prod).
  - S'execute avec le role sentrix_migrator, jamais sentrix_app.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import asyncpg

__all__ = ["Migration", "MigrationDriftError", "discover", "apply_all"]

_FILENAME_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class MigrationDriftError(RuntimeError):
    """Une migration deja appliquee a ete modifiee sur disque."""


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def discover(directory: Path) -> list[Migration]:
    """Liste triee des migrations d'un repertoire."""
    migrations: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME_RE.match(path.name)
        if match is None:
            raise ValueError(f"nom de migration invalide : {path.name} (attendu NNNN_nom.sql)")
        migrations.append(
            Migration(
                version=match.group(1),
                name=path.stem,
                path=path,
                sql=path.read_text(encoding="utf-8"),
            )
        )

    versions = [m.version for m in migrations]
    if len(set(versions)) != len(versions):
        raise ValueError("numeros de migration dupliques")
    return migrations


async def _ensure_tracking_table(conn: asyncpg.Connection[asyncpg.Record]) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    text        PRIMARY KEY,
            checksum   text        NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


async def apply_all(conn: asyncpg.Connection[asyncpg.Record], directory: Path) -> list[str]:
    """Applique les migrations manquantes. Retourne les versions appliquees."""
    migrations = discover(directory)
    await _ensure_tracking_table(conn)

    rows = await conn.fetch("SELECT version, checksum FROM schema_migrations")
    applied: dict[str, str] = {r["version"]: r["checksum"] for r in rows}

    # Verification de derive AVANT toute application.
    for migration in migrations:
        known = applied.get(migration.version)
        if known is not None and known != migration.checksum:
            raise MigrationDriftError(
                f"migration {migration.version} ({migration.name}) modifiee apres application : "
                f"checksum attendu {known}, calcule {migration.checksum}"
            )

    newly_applied: list[str] = []
    for migration in migrations:
        if migration.version in applied:
            continue
        # Chaque migration dans sa propre transaction : un echec n'applique
        # jamais partiellement un fichier.
        async with conn.transaction():
            await conn.execute(migration.sql)
            await conn.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES ($1, $2)",
                migration.version,
                migration.checksum,
            )
        newly_applied.append(migration.version)

    return newly_applied
