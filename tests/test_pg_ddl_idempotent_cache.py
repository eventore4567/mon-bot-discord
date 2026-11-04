"""04/11/2026 : un « CREATE … IF NOT EXISTS » déjà réussi n'est plus renvoyé à Postgres.

Les cogs rejouent leurs CREATE TABLE à chaque commande. En production (Postgres),
chacun prenait le verrou d'écriture puis relisait le catalogue : jusqu'à 1,2 s
mesuré, et /setup s'ouvrait en 3 à 5 s.
"""
from __future__ import annotations

import asyncio

from database.pg_backend import PgConnection, PgCursor


def _connexion():
    conn = PgConnection(main=object(), pool=object(), schema="public")
    envoyes: list[str] = []
    catalogue: list[str] = []

    async def run(target, translated, params, *, pooled=False):
        envoyes.append(" ".join(translated.sql.split()))
        return PgCursor()

    async def refresh(sql):
        catalogue.append(sql)

    conn._run = run
    conn._refresh_after_ddl = refresh
    return conn, envoyes, catalogue


CREATE = "CREATE TABLE IF NOT EXISTS sentrix_music_settings (guild_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1)"
INDEX = "CREATE INDEX IF NOT EXISTS idx_music_guild ON sentrix_music_settings(guild_id)"


def test_un_create_if_not_exists_n_est_envoye_qu_une_fois():
    conn, envoyes, catalogue = _connexion()

    async def scenario():
        for _ in range(5):
            await conn.execute(CREATE)
            await conn.execute(INDEX)

    asyncio.run(scenario())
    assert len(envoyes) == 2
    assert len(catalogue) == 2


def test_un_drop_ou_alter_vide_le_cache():
    conn, envoyes, _ = _connexion()

    async def scenario():
        await conn.execute(CREATE)
        await conn.execute("DROP TABLE IF EXISTS sentrix_music_settings")
        await conn.execute(CREATE)
        await conn.execute("ALTER TABLE sentrix_music_settings ADD COLUMN volume INTEGER")
        await conn.execute(CREATE)

    asyncio.run(scenario())
    assert sum(1 for sql in envoyes if sql.startswith("CREATE TABLE")) == 3


def test_un_create_en_echec_sera_retente():
    conn, envoyes, _ = _connexion()
    essais = {"n": 0}
    run_ok = conn._run

    async def run(target, translated, params, *, pooled=False):
        essais["n"] += 1
        if essais["n"] == 1:
            raise RuntimeError("connexion perdue")
        return await run_ok(target, translated, params, pooled=pooled)

    conn._run = run

    async def scenario():
        try:
            await conn.execute(CREATE)
        except RuntimeError:
            pass
        await conn.execute(CREATE)
        await conn.execute(CREATE)

    asyncio.run(scenario())
    assert essais["n"] == 2


def test_les_ecritures_ordinaires_ne_sont_jamais_mises_en_cache():
    conn, envoyes, _ = _connexion()

    async def begin():
        conn._tx = None

    conn._begin = begin

    async def scenario():
        for _ in range(3):
            await conn.execute("UPDATE sentrix_music_settings SET enabled=1 WHERE guild_id=?", (1,))

    asyncio.run(scenario())
    assert len(envoyes) == 3
