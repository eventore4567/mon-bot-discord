"""services/tickets.py::count_genuinely_open_tickets() — extrait de
cogs/tickets.py, où elle était déjà partagée par deux points d'entrée
(Tickets.start_ticket_flow et cogs/ticket_claim_security.py). Comportement
inchangé par l'extraction : cogs/tickets.py importe et ré-expose cette même
fonction (voir tests/test_ticket_reopen_after_channel_deleted.py, qui
continue de l'appeler via cogs.tickets et reste vert après ce déplacement).
Ce fichier couvre uniquement le service directement, comme pour les autres
extractions Core V2 (services/economy.py, services/levels.py)."""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database
from services import tickets as tickets_service


class _FakeBot:
    def __init__(self, db: Database):
        self.db = db


class _FakeGuild:
    def __init__(self, id_: int, existing_channel_ids: set[int]):
        self.id = id_
        self._existing = existing_channel_ids

    def get_channel(self, channel_id: int):
        return object() if channel_id in self._existing else None


class CountGenuinelyOpenTicketsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self._tmpdir.name, "sentrix-test.db"))
        await self.db.connect()
        self.bot = _FakeBot(self.db)

    async def asyncTearDown(self):
        await self.db._conn.close()
        self._tmpdir.cleanup()

    async def _insert_ticket(self, *, guild_id, channel_id, user_id, type_id, status="ouvert"):
        await self.db.execute(
            "INSERT INTO tickets (guild_id, channel_id, user_id, type_id, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (guild_id, channel_id, user_id, type_id, status),
        )

    async def test_ne_compte_rien_sans_ticket(self):
        guild = _FakeGuild(id_=1, existing_channel_ids=set())
        count = await tickets_service.count_genuinely_open_tickets(self.bot, guild, user_id=42, type_id=7)
        self.assertEqual(count, 0)

    async def test_compte_un_ticket_dont_le_salon_existe(self):
        guild = _FakeGuild(id_=1, existing_channel_ids={999})
        await self._insert_ticket(guild_id=1, channel_id=999, user_id=42, type_id=7)
        count = await tickets_service.count_genuinely_open_tickets(self.bot, guild, user_id=42, type_id=7)
        self.assertEqual(count, 1)

    async def test_ignore_et_repare_un_ticket_dont_le_salon_a_disparu(self):
        guild = _FakeGuild(id_=1, existing_channel_ids=set())
        await self._insert_ticket(guild_id=1, channel_id=999, user_id=42, type_id=7)
        count = await tickets_service.count_genuinely_open_tickets(self.bot, guild, user_id=42, type_id=7)
        self.assertEqual(count, 0)
        row = await self.db.fetchone("SELECT status FROM tickets WHERE channel_id = 999")
        self.assertEqual(row["status"], "supprime")

    async def test_ignore_les_tickets_fermes(self):
        guild = _FakeGuild(id_=1, existing_channel_ids={999})
        await self._insert_ticket(guild_id=1, channel_id=999, user_id=42, type_id=7, status="ferme")
        count = await tickets_service.count_genuinely_open_tickets(self.bot, guild, user_id=42, type_id=7)
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
