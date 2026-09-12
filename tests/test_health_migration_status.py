"""Milestone 4 (Observabilité), en avance sur la roadmap : /health n'exposait
aucun état du système de migrations (database/migrations.py, Milestone 1) —
impossible de savoir, depuis l'extérieur, si les migrations ont bien tourné
sur l'instance qui répond, ou si schema_migrations existe même. Ajouté
migration_version / migrations_available à la réponse /health.
"""
from __future__ import annotations

import asyncio

from database.db import Database
from web import health_runtime_v45 as health


async def _make_db(tmp_path) -> Database:
    db = Database(str(tmp_path / "health.db"))
    await db.connect()
    return db


class _FakeBot:
    def __init__(self, db):
        self.db = db


def test_migration_state_reports_zero_when_no_numbered_migration_exists(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        try:
            bot = _FakeBot(db)
            version, available = await health._migration_state(bot)
            assert version == 0
            assert available == 0
        finally:
            await db.close()

    asyncio.run(run())


def test_migration_state_reflects_an_applied_numbered_migration(tmp_path, monkeypatch):
    from database import migrations as db_migrations

    async def run():
        db = await _make_db(tmp_path)
        try:
            async def _noop(conn):
                pass

            monkeypatch.setattr(
                db_migrations, "MIGRATIONS", [db_migrations.Migration(1, "test", _noop)]
            )
            await db_migrations.run(db._conn, [])
            await db._conn.commit()

            bot = _FakeBot(db)
            version, available = await health._migration_state(bot)
            assert version == 1
            assert available == 1
        finally:
            await db.close()

    asyncio.run(run())


def test_migration_state_returns_none_when_db_not_connected():
    class _Disconnected:
        db = None

    async def run():
        return await health._migration_state(_Disconnected())

    assert asyncio.run(run()) is None


def test_snapshot_includes_migration_fields_and_never_raises(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        try:
            bot = _FakeBot(db)
            bot.guilds = []
            bot.latency = 0.05
            bot.is_ready = lambda: True
            data = await health._snapshot(bot, object())
            assert "migration_version" in data
            assert "migrations_available" in data
            assert data["migration_version"] == 0
        finally:
            await db.close()

    asyncio.run(run())
