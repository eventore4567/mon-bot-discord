"""cogs/ticket_claim_security.py::_safe_ticket_log() n'est plus qu'un
adaptateur mince vers services/tickets.py::safe_ticket_log() (il n'avait que
cog.bot à passer). Ce test verrouille juste le branchement — le
comportement lui-même est couvert par tests/test_services_tickets.py::
SafeTicketLogTests."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from cogs import ticket_claim_security


class SafeTicketLogDelegationTests(unittest.IsolatedAsyncioTestCase):
    async def test_delegue_bien_au_service_avec_cog_bot(self):
        bot = SimpleNamespace()
        cog = SimpleNamespace(bot=bot)
        guild = SimpleNamespace(id=1)
        embed = discord.Embed(title="Test")

        with patch.object(
            ticket_claim_security.tickets_service, "safe_ticket_log", AsyncMock(return_value=True)
        ) as safe_log:
            result = await ticket_claim_security._safe_ticket_log(cog, guild, "ticket_close", embed, event_key="x")

        self.assertTrue(result)
        safe_log.assert_awaited_once_with(bot, guild, "ticket_close", embed, event_key="x")


if __name__ == "__main__":
    unittest.main()
