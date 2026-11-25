"""Réglages relus par chaque commande : une lecture en base, puis la mémoire (25/11/2026).

Jayden : « chaque commande se lance en retard ». Chaque commande relisait les
salons bloqués / autorisés et les règles par rôle avant de répondre : autant
d'allers-retours PostgreSQL. Ils sont désormais gardés en mémoire et oubliés
dès qu'une écriture touche ces tables.
"""
import asyncio

from database.db import Database


def _compter(db):
    appels = []
    original = db._conn.execute

    async def execute(q, *a, **k):
        appels.append(str(q))
        return await original(q, *a, **k)

    db._conn.execute = execute
    return appels


def test_reglages_lus_une_fois_puis_oublies_a_l_ecriture(tmp_path):
    async def scenario():
        db = Database(str(tmp_path / "t.db"))
        await db.connect()
        try:
            appels = _compter(db)
            q = "SELECT 1 FROM command_blocked_channels WHERE guild_id = ? AND channel_id = ? LIMIT 1"
            for _ in range(5):
                assert await db.fetchone(q, (1, 2)) is None
            assert sum("command_blocked_channels" in a for a in appels) == 1, "relu à chaque commande"

            # Un CREATE TABLE IF NOT EXISTS (rejoué par les cogs) ne vide pas la mémoire.
            await db.execute(
                "CREATE TABLE IF NOT EXISTS category_allowed_channels "
                "(guild_id INTEGER, category TEXT, channel_id INTEGER)"
            )
            await db.fetchone(q, (1, 2))
            assert sum("command_blocked_channels" in a and a.lstrip().startswith("SELECT") for a in appels) == 1

            # Une écriture : la lecture suivante voit le nouveau salon bloqué.
            await db.execute("INSERT INTO command_blocked_channels (guild_id, channel_id) VALUES (?, ?)", (1, 2))
            assert await db.fetchone(q, (1, 2)) is not None
            assert await db.fetchall(
                "SELECT channel_id FROM command_blocked_channels WHERE guild_id = ?", (1,)
            )
        finally:
            await db.close()

    asyncio.run(scenario())
