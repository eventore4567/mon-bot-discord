"""+ticket-priority — Milestone 3 (Modules avancés).

"priority" existe dans le schéma tickets depuis toujours (database/db.py) et
est déjà lu par le dashboard (web/ticket_center_v35.py), mais rien ne
l'écrivait jamais après la création du ticket (toujours 'normale',
cogs/tickets.py::INSERT INTO tickets) — un champ mort en pratique. Cette
commande est la première à réellement le modifier. Test d'exécution réel :
vraie base SQLite, vrai cog (même convention que
tests/test_ticket_reopen_commands_consistency.py).
"""
from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database, now
from cogs.tickets import Tickets, TICKET_PRIORITY_LABELS


class _FakeBot:
    def __init__(self, db: Database):
        self.db = db


class TicketPriorityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self._tmpdir.name, "sentrix-test.db"))
        await self.db.connect()
        self.bot = _FakeBot(self.db)
        self.cog = Tickets(self.bot)

    async def asyncTearDown(self):
        await self.db._conn.close()
        self._tmpdir.cleanup()

    async def _insert_open_ticket(self, *, guild_id=1, channel_id=100, user_id=2):
        await self.db.execute(
            "INSERT INTO tickets (guild_id, channel_id, user_id, status, priority, created_at, last_activity_at) "
            "VALUES (?, ?, ?, 'ouvert', 'normale', ?, ?)",
            (guild_id, channel_id, user_id, now(), now()),
        )
        row = await self.db.fetchone("SELECT last_insert_rowid() AS id")
        return row["id"]

    def _fake_ctx(self, channel_id):
        sent = {}

        async def fake_send(*args, **kwargs):
            sent["called"] = True

        return SimpleNamespace(channel=SimpleNamespace(id=channel_id), send=AsyncMock(side_effect=fake_send)), sent

    async def test_sets_priority_on_a_real_ticket(self):
        ticket_id = await self._insert_open_ticket(channel_id=100)
        ctx, _ = self._fake_ctx(100)

        await Tickets.ticket_priority.callback(self.cog, ctx, "haute")

        row = await self.db.fetchone("SELECT priority FROM tickets WHERE id = ?", (ticket_id,))
        self.assertEqual(row["priority"], "haute")

    async def test_is_case_insensitive_and_trims_whitespace(self):
        await self._insert_open_ticket(channel_id=100)
        ctx, _ = self._fake_ctx(100)

        await Tickets.ticket_priority.callback(self.cog, ctx, "  URGENTE  ")

        row = await self.db.fetchone("SELECT priority FROM tickets WHERE channel_id = 100")
        self.assertEqual(row["priority"], "urgente")

    async def test_rejects_unknown_priority_and_does_not_write(self):
        await self._insert_open_ticket(channel_id=100)
        ctx, _ = self._fake_ctx(100)

        await Tickets.ticket_priority.callback(self.cog, ctx, "catastrophique")

        row = await self.db.fetchone("SELECT priority FROM tickets WHERE channel_id = 100")
        self.assertEqual(row["priority"], "normale")

    async def test_rejects_when_channel_is_not_a_ticket(self):
        ctx, _ = self._fake_ctx(999)

        # Ne doit pas lever, seulement refuser proprement.
        await Tickets.ticket_priority.callback(self.cog, ctx, "haute")

        rows = await self.db.fetchall("SELECT * FROM tickets")
        self.assertEqual(rows, [])

    async def test_every_advertised_priority_label_is_settable(self):
        for niveau in TICKET_PRIORITY_LABELS:
            with self.subTest(niveau=niveau):
                await self.db.execute("DELETE FROM tickets")
                await self._insert_open_ticket(channel_id=100)
                ctx, _ = self._fake_ctx(100)

                await Tickets.ticket_priority.callback(self.cog, ctx, niveau)

                row = await self.db.fetchone("SELECT priority FROM tickets WHERE channel_id = 100")
                self.assertEqual(row["priority"], niveau)
