"""+ticket-tags — Milestone 3 (Modules avancés).

"tags" n'existait pas du tout avant cette session : colonne ajoutée dans
database/db.py::SCHEMA, réconciliée automatiquement par database/
migrations.py (Milestone 1) — aucune migration numérotée écrite à la main,
exactement le scénario que ce système a été construit pour couvrir. Test
d'exécution réel : vraie base SQLite, vrai cog (même convention que
tests/test_ticket_priority.py).
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database, now
from cogs.tickets import Tickets, TICKET_TAG_MAX_COUNT, TICKET_TAG_MAX_LENGTH


class _FakeBot:
    def __init__(self, db: Database):
        self.db = db


class TicketTagsTests(unittest.IsolatedAsyncioTestCase):
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
            "INSERT INTO tickets (guild_id, channel_id, user_id, status, created_at, last_activity_at) "
            "VALUES (?, ?, ?, 'ouvert', ?, ?)",
            (guild_id, channel_id, user_id, now(), now()),
        )
        row = await self.db.fetchone("SELECT last_insert_rowid() AS id")
        return row["id"]

    def _fake_ctx(self, channel_id):
        return SimpleNamespace(channel=SimpleNamespace(id=channel_id), send=AsyncMock())

    async def _tags_for(self, channel_id):
        row = await self.db.fetchone("SELECT tags FROM tickets WHERE channel_id = ?", (channel_id,))
        return json.loads(row["tags"])

    async def test_new_ticket_starts_with_no_tags(self):
        await self._insert_open_ticket(channel_id=100)
        self.assertEqual(await self._tags_for(100), [])

    async def test_sets_tags_from_comma_separated_input(self):
        await self._insert_open_ticket(channel_id=100)
        ctx = self._fake_ctx(100)

        await Tickets.ticket_tags.callback(self.cog, ctx, tags="paiement, urgent, vip")

        self.assertEqual(await self._tags_for(100), ["paiement", "urgent", "vip"])

    async def test_empty_input_clears_all_tags(self):
        await self._insert_open_ticket(channel_id=100)
        ctx = self._fake_ctx(100)
        await Tickets.ticket_tags.callback(self.cog, ctx, tags="a,b")

        await Tickets.ticket_tags.callback(self.cog, ctx, tags="")

        self.assertEqual(await self._tags_for(100), [])

    async def test_deduplicates_case_insensitively_keeping_first_spelling(self):
        await self._insert_open_ticket(channel_id=100)
        ctx = self._fake_ctx(100)

        await Tickets.ticket_tags.callback(self.cog, ctx, tags="VIP, vip, Vip")

        self.assertEqual(await self._tags_for(100), ["VIP"])

    async def test_rejects_a_tag_longer_than_the_limit_without_writing(self):
        await self._insert_open_ticket(channel_id=100)
        ctx = self._fake_ctx(100)
        too_long = "x" * (TICKET_TAG_MAX_LENGTH + 1)

        await Tickets.ticket_tags.callback(self.cog, ctx, tags=f"ok,{too_long}")

        self.assertEqual(await self._tags_for(100), [])

    async def test_rejects_too_many_tags_without_writing(self):
        await self._insert_open_ticket(channel_id=100)
        ctx = self._fake_ctx(100)
        trop = ",".join(f"tag{i}" for i in range(TICKET_TAG_MAX_COUNT + 1))

        await Tickets.ticket_tags.callback(self.cog, ctx, tags=trop)

        self.assertEqual(await self._tags_for(100), [])

    async def test_rejects_when_channel_is_not_a_ticket(self):
        ctx = self._fake_ctx(999)

        await Tickets.ticket_tags.callback(self.cog, ctx, tags="vip")

        rows = await self.db.fetchall("SELECT * FROM tickets")
        self.assertEqual(rows, [])
