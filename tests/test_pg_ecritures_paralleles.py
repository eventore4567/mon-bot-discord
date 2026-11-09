"""09/11/2026 : les écritures isolées partent sur le pool, en parallèle ; les
transactions explicites restent sur la connexion principale."""
from __future__ import annotations

import asyncio
import os

import pytest

from database import pg_backend
from database.pg_backend import PgConnection


class _ConnFactice:
    def __init__(self, journal):
        self.journal = journal

    async def prepare(self, sql):
        class _Stmt:
            @staticmethod
            def get_parameters():
                return []
        return _Stmt()

    async def execute(self, sql, *args):
        self.journal.append(("pool-execute", sql))
        return "UPDATE 3"

    async def fetch(self, sql, *args):
        self.journal.append(("pool-fetch", sql))
        return []


class _PoolFactice:
    def __init__(self, journal):
        self.journal = journal

    def acquire(self):
        journal = self.journal

        class _Ctx:
            async def __aenter__(self_inner):
                return _ConnFactice(journal)

            async def __aexit__(self_inner, *exc):
                return False
        return _Ctx()


def test_une_ecriture_isolee_part_sur_le_pool(monkeypatch):
    monkeypatch.setattr(pg_backend, "_ECRITURES_EN_PARALLELE", True)
    journal: list = []
    conn = PgConnection(main=object(), pool=_PoolFactice(journal), schema="public")
    curseur = asyncio.run(conn.execute_and_commit("UPDATE levels SET xp = xp + 1 WHERE guild_id = ?", (1,)))
    assert journal and journal[0][0] == "pool-execute"
    assert curseur.rowcount == 3


def test_desactivable_par_variable(monkeypatch):
    monkeypatch.setattr(pg_backend, "_ECRITURES_EN_PARALLELE", False)
    journal: list = []
    conn = PgConnection(main=object(), pool=_PoolFactice(journal), schema="public")
    appels = []

    async def run(target, translated, params, *, pooled=False):
        appels.append(target)
        return pg_backend.PgCursor()

    conn._run = run
    asyncio.run(conn.execute_and_commit("UPDATE levels SET xp = 1 WHERE guild_id = ?", (1,)))
    assert not journal and appels  # ancienne voie : connexion principale


PG_URL = os.getenv("SENTRIX_TEST_PG_URL")


@pytest.mark.skipif(not PG_URL, reason="SENTRIX_TEST_PG_URL absent (PostgreSQL réel)")
def test_sur_postgres_reel_les_compteurs_restent_exacts(monkeypatch):
    monkeypatch.setattr(pg_backend, "_ECRITURES_EN_PARALLELE", True)

    async def scenario():
        conn = await PgConnection.connect(PG_URL, schema="test_ecritures_paralleles", pool_size=8)
        try:
            await conn.execute("DROP TABLE IF EXISTS compteurs")
            await conn.execute("CREATE TABLE IF NOT EXISTS compteurs (g INTEGER, u INTEGER, n INTEGER, PRIMARY KEY (g, u))")
            await asyncio.gather(*(
                conn.execute_and_commit(
                    "INSERT INTO compteurs (g, u, n) VALUES (?, ?, 1) ON CONFLICT(g, u) DO UPDATE SET n = n + 1",
                    (1, i % 7),
                )
                for i in range(140)
            ))
            total = await (await conn.execute("SELECT SUM(n) AS total FROM compteurs")).fetchone()
            maj = await conn.execute_and_commit("UPDATE compteurs SET n = n WHERE g = ?", (1,))
            return int(total["total"]), maj.rowcount
        finally:
            await conn.close()

    total, lignes = asyncio.run(scenario())
    assert total == 140 and lignes == 7
