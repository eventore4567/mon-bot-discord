"""Milestone 5 (Scale) : idx_economy_tx_sender_time / idx_economy_tx_receiver_time
vivaient uniquement dans cogs/sentrix_v22.py::cog_load — une base neuve ou
restaurée où ce cog échoue à charger n'avait jamais ces index, alors que
economy_transactions est filtrée par sender_id/receiver_id dans plusieurs
endroits (database/db.py, cogs/platform_v4.py). Déplacés dans le schéma
canonique (database/db.py::INDEXES).
"""
from __future__ import annotations

import asyncio

from database.db import Database


def test_sender_and_receiver_indexes_exist_on_a_fresh_database(tmp_path):
    async def run():
        db = Database(str(tmp_path / "idx.db"))
        try:
            await db.connect()
            cur = await db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='economy_transactions'"
            )
            names = {row[0] for row in await cur.fetchall()}
            assert "idx_economy_tx_sender_time" in names
            assert "idx_economy_tx_receiver_time" in names
        finally:
            await db.close()

    asyncio.run(run())


def test_sentrix_v22_creating_the_same_indexes_again_does_not_error(tmp_path):
    """cogs/sentrix_v22.py continue de les créer aussi (transition volontairement
    non-agressive) : CREATE INDEX IF NOT EXISTS doit rester un no-op silencieux."""
    async def run():
        db = Database(str(tmp_path / "idx2.db"))
        try:
            await db.connect()
            await db._conn.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_economy_tx_sender_time
                  ON economy_transactions (guild_id, sender_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_economy_tx_receiver_time
                  ON economy_transactions (guild_id, receiver_id, created_at);
                """
            )
        finally:
            await db.close()

    asyncio.run(run())
