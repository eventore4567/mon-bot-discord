"""Préférence de fermeture des tickets : opt-out sans popup, conservé par serveur."""
from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database
from cogs.tickets import Tickets, ask_close_reason, set_ask_close_reason


class TicketCloseReasonPreferenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.tmpdir.name, "tickets.db"))
        await self.db.connect()
        self.bot = SimpleNamespace(db=self.db)

    async def asyncTearDown(self):
        await self.db.close()
        self.tmpdir.cleanup()

    async def test_default_and_per_server_persistence(self):
        self.assertTrue(await ask_close_reason(self.bot, 101))
        self.assertTrue(await ask_close_reason(self.bot, 202))
        await set_ask_close_reason(self.bot, 101, False)
        self.assertFalse(await ask_close_reason(self.bot, 101))
        self.assertTrue(await ask_close_reason(self.bot, 202))
        await set_ask_close_reason(self.bot, 101, True)
        self.assertTrue(await ask_close_reason(self.bot, 101))

    async def test_btn_close_skips_modal_only_when_configured(self):
        cog = Tickets.__new__(Tickets)
        cog.bot = self.bot
        cog.close_ticket = AsyncMock()
        response = SimpleNamespace(send_modal=AsyncMock(), defer=AsyncMock())
        interaction = SimpleNamespace(guild=SimpleNamespace(id=101), response=response)
        ticket = {"id": 77}

        await cog.btn_close(interaction, ticket)
        response.send_modal.assert_awaited_once()
        response.defer.assert_not_awaited()
        cog.close_ticket.assert_not_awaited()

        response.send_modal.reset_mock()
        await set_ask_close_reason(self.bot, 101, False)
        await cog.btn_close(interaction, ticket)
        response.send_modal.assert_not_awaited()
        response.defer.assert_awaited_once_with(ephemeral=True)
        cog.close_ticket.assert_awaited_once_with(interaction, 77, "Non précisée")


if __name__ == "__main__":
    unittest.main()
