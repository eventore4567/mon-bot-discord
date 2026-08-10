"""Acces PostgreSQL et contexte tenant.

POINT CRITIQUE DE P0 - a lire avant toute modification.

Le contexte tenant est pose UNIQUEMENT via set_config('app.current_org', $1, true),
strictement a l'interieur d'une transaction explicite.

Pourquoi pas `SET app.current_org = ...` :
    Avec PgBouncer en mode transaction, les connexions sont recyclees entre
    transactions. Un SET persistant fuit vers la transaction suivante, donc vers
    UN AUTRE TENANT. Faille d'isolation totale, silencieuse, tres difficile a
    diagnostiquer apres coup.

Pourquoi set_config(..., true) plutot que `SET LOCAL` :
    Strictement equivalent (is_local=true), mais parametrable. `SET LOCAL` ne
    supporte pas les parametres de requete et imposerait une interpolation de
    chaine - donc un risque d'injection sur un chemin critique de securite.

Toute cette logique vit ici et NULLE PART AILLEURS. Le code metier ne pose
jamais le contexte tenant lui-meme. Un test (tests/unit/test_no_persistent_set.py)
verifie mecaniquement cette regle sur l'ensemble du depot.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Self
from uuid import UUID

import asyncpg

__all__ = ["Database", "TenantContextError"]


class TenantContextError(RuntimeError):
    """Contexte tenant utilise de facon incorrecte."""


class Database:
    """Pool asyncpg + acces transactionnels tenant / admin."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 10) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: asyncpg.Pool[asyncpg.Record] | None = None

    async def connect(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=self._min_size,
                max_size=self._max_size,
                # Les statements prepares nommes sont incompatibles avec
                # PgBouncer en mode transaction.
                statement_cache_size=0,
            )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool[asyncpg.Record]:
        if self._pool is None:
            raise TenantContextError("Database.connect() n'a pas ete appele")
        return self._pool

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    @asynccontextmanager
    async def tenant_tx(self, org_id: UUID) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
        """Transaction avec contexte tenant pose.

        Le contexte est valable pour la duree de la transaction UNIQUEMENT.
        A la sortie (commit ou rollback), PostgreSQL le retire automatiquement :
        la connexion peut etre rendue au pool sans fuite vers un autre tenant.
        """
        if not isinstance(org_id, UUID):
            raise TenantContextError("org_id doit etre un UUID")

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('app.current_org', $1, true)",
                    str(org_id),
                )
                yield conn

    @asynccontextmanager
    async def admin_tx(self) -> AsyncIterator[asyncpg.Connection[asyncpg.Record]]:
        """Transaction SANS contexte tenant.

        Reservee aux operations non tenant (authentification, referentiel des
        cellules, migrations). Toute requete touchant une table sous RLS
        echouera en 42704 - c'est voulu : defaillance fermee.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                yield conn


def dsn_from_env(var: str = "DATABASE_URL") -> str:
    dsn = os.environ.get(var)
    if not dsn:
        raise RuntimeError(f"variable d'environnement {var} absente")
    return dsn
