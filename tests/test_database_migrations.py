"""Milestone 1 (SentriX Core Reliability) : tests de régression pour
database/migrations.py.

Contexte : avant ce système, une restauration PostgreSQL plus ancienne que le
code qui tourne pouvait manquer une colonne récente sur n'importe laquelle des
~79 tables du bot, et la première commande qui la touchait plantait avec
`sqlite3.OperationalError: no such column: xxx` — exactement la classe de bug
que ce milestone doit éliminer. L'ancien Database._migrate() ne couvrait que 7
tables listées à la main ; ces tests vérifient spécifiquement une colonne dont
la table (guild_config) figure certes dans cette liste, mais en s'assurant que
c'est la NOUVELLE réconciliation générique (pas l'ancien code) qui la corrige,
et que le mécanisme est bien générique (pas câblé table par table).

Ce fichier n'utilise pas @pytest.mark.asyncio : pytest-asyncio n'est pas
installé dans ce dépôt (voir tests/test_v101_command_runtime.py, seul endroit
où ce marqueur est utilisé, et ses 2 tests échouent pour cette raison exacte).
Convention déjà établie ailleurs (tests/test_v17_error_transport_reference_
leak.py) : fonctions de test synchrones, corps async lancé via asyncio.run().
"""
from __future__ import annotations

import asyncio
import sqlite3

import aiosqlite

from database import migrations as db_migrations
from database.db import GAME_TRANSACTIONS_SCHEMA, LOG_CONFIG_SCHEMA, SCHEMA

SCHEMA_SCRIPTS = [SCHEMA, GAME_TRANSACTIONS_SCHEMA, LOG_CONFIG_SCHEMA]


def _strip_column(create_table_sql: str, column: str) -> str:
    """Retire la ligne définissant `column` (peu importe la table), pour simuler
    une base créée avant l'ajout de cette colonne."""
    lines = create_table_sql.splitlines()
    return "\n".join(line for line in lines if not line.strip().startswith(f"{column} "))


def test_reconcile_adds_missing_column_and_preserves_existing_data(tmp_path):
    old_schema = _strip_column(SCHEMA, "welcome_image_url")
    assert "welcome_image_url" not in old_schema
    assert "welcome_image_url" in SCHEMA

    async def run():
        conn = await aiosqlite.connect(str(tmp_path / "old.db"))
        conn.row_factory = aiosqlite.Row
        try:
            await conn.executescript(old_schema)
            await conn.execute(
                "INSERT INTO guild_config (guild_id, prefix) VALUES (?, ?)", (123456789, "!")
            )
            await conn.commit()

            cur = await conn.execute("PRAGMA table_info(guild_config)")
            columns_before = {row[1] for row in await cur.fetchall()}
            assert "welcome_image_url" not in columns_before

            added = await db_migrations.reconcile_additive_columns(conn, SCHEMA_SCRIPTS)
            await conn.commit()
            assert "guild_config.welcome_image_url" in added

            cur = await conn.execute("PRAGMA table_info(guild_config)")
            columns_after = {row[1] for row in await cur.fetchall()}
            assert "welcome_image_url" in columns_after

            cur = await conn.execute(
                "SELECT prefix, welcome_image_url FROM guild_config WHERE guild_id = ?",
                (123456789,),
            )
            row = await cur.fetchone()
            assert row["prefix"] == "!"
            assert row["welcome_image_url"] is None
        finally:
            await conn.close()

    asyncio.run(run())


def test_reconcile_is_idempotent(tmp_path):
    async def run():
        conn = await aiosqlite.connect(str(tmp_path / "current.db"))
        try:
            for script in SCHEMA_SCRIPTS:
                await conn.executescript(script)
            await conn.commit()

            first_pass = await db_migrations.reconcile_additive_columns(conn, SCHEMA_SCRIPTS)
            await conn.commit()
            second_pass = await db_migrations.reconcile_additive_columns(conn, SCHEMA_SCRIPTS)

            assert first_pass == []
            assert second_pass == []
        finally:
            await conn.close()

    asyncio.run(run())


def test_reconcile_never_touches_a_table_that_does_not_exist_yet(tmp_path):
    """Les CREATE TABLE IF NOT EXISTS (déjà exécutés avant, dans
    Database.connect()) créent une table manquante — la réconciliation ne doit
    jamais tenter d'ALTER une table absente côté réel."""
    async def run():
        conn = await aiosqlite.connect(str(tmp_path / "empty.db"))
        try:
            added = await db_migrations.reconcile_additive_columns(conn, SCHEMA_SCRIPTS)
            assert added == []
        finally:
            await conn.close()

    asyncio.run(run())


def test_run_creates_schema_migrations_table_and_records_numbered_migrations(tmp_path, monkeypatch):
    async def run():
        conn = await aiosqlite.connect(str(tmp_path / "versioned.db"))
        try:
            for script in SCHEMA_SCRIPTS:
                await conn.executescript(script)
            await conn.commit()

            applied: list[int] = []

            async def _fake_apply(c):
                applied.append(1)
                await c.execute("CREATE TABLE IF NOT EXISTS _test_marker (id INTEGER PRIMARY KEY)")

            fake_migration = db_migrations.Migration(1, "test_marker", _fake_apply)
            monkeypatch.setattr(db_migrations, "MIGRATIONS", [fake_migration])

            await db_migrations.run(conn, SCHEMA_SCRIPTS)
            await conn.commit()

            assert applied == [1]
            version = await db_migrations.current_version(conn)
            assert version == 1

            # Exécution idempotente : un second appel ne doit pas réappliquer
            # une migration déjà enregistrée.
            await db_migrations.run(conn, SCHEMA_SCRIPTS)
            assert applied == [1]
        finally:
            await conn.close()

    asyncio.run(run())


def test_real_boot_survives_a_database_missing_a_recent_column(tmp_path):
    """Reproduction bout-en-bout du scénario réel : Database.connect() sur un
    fichier créé avec un schéma antérieur à l'ajout d'une colonne ne doit jamais
    lever sqlite3.OperationalError: no such column."""
    from database.db import Database

    path = tmp_path / "stale_snapshot.db"
    old_schema = _strip_column(SCHEMA, "welcome_image_url")
    raw = sqlite3.connect(str(path))
    try:
        raw.executescript(old_schema)
        raw.executescript(GAME_TRANSACTIONS_SCHEMA)
        raw.executescript(LOG_CONFIG_SCHEMA)
        raw.execute("INSERT INTO guild_config (guild_id, prefix) VALUES (?, ?)", (999, "+"))
        raw.commit()
    finally:
        raw.close()

    async def run():
        db = Database(str(path))
        try:
            await db.connect()
            cur = await db._conn.execute(
                "SELECT welcome_image_url FROM guild_config WHERE guild_id = ?", (999,)
            )
            row = await cur.fetchone()
            assert row is not None
            assert row["welcome_image_url"] is None
        finally:
            await db.close()

    asyncio.run(run())
