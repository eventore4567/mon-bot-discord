"""Les commandes personnalisées d'avant les droits par commande restent ouvertes à tous."""
import asyncio
import os
import tempfile
from types import SimpleNamespace

from cogs import platform_v4
from database.db import Database


def test_legacy_commands_get_everyone_once_and_new_ones_stay_admin_only():
    async def scenario():
        with tempfile.TemporaryDirectory() as folder:
            db = Database(os.path.join(folder, "t.db"))
            await db.connect()
            bot = SimpleNamespace(db=db)
            for statement in platform_v4.SCHEMA.split(";"):
                if statement.strip():
                    await db.execute(statement.strip())
            insert = ("INSERT INTO platform_custom_commands (guild_id,name,response,created_at,updated_at) "
                      "VALUES (?,?,?,?,?)")
            old = platform_v4.CUSTOM_ACCESS_INTRODUCED_AT - 86400
            new = platform_v4.CUSTOM_ACCESS_INTRODUCED_AT + 3600
            await db.execute(insert, (1, "ancienne", "ok", old, old))
            await db.execute(insert, (1, "nouvelle", "ok", new, new))

            await platform_v4._ensure_schema(bot)
            rows = await db.fetchall(
                "SELECT c.name, a.subject_type FROM platform_custom_command_access a "
                "JOIN platform_custom_commands c ON c.id = a.command_id"
            )
            assert [(r["name"], r["subject_type"]) for r in rows] == [("ancienne", "everyone")]

            # Un administrateur retire ensuite le droit : le redémarrage ne le remet pas.
            await db.execute("DELETE FROM platform_custom_command_access")
            await platform_v4._ensure_schema(bot)
            assert await db.fetchall("SELECT * FROM platform_custom_command_access") == []
            await db.close()

    asyncio.run(scenario())
