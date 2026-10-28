"""La commande healthcheck utilise le rendu condensé, sans changer les autres diagnostics."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
from cogs import v17_health


class CompactHealthcheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_healthcheck_uses_compact_embed(self):
        cog = v17_health.V17Health.__new__(v17_health.V17Health)
        bot = SimpleNamespace()
        cog.bot = bot
        guild = SimpleNamespace(id=100)
        ctx = SimpleNamespace(guild=guild)
        embed = discord.Embed(title="Santé SentriX")

        with (
            patch.object(v17_health, "build_health_embed", new_callable=AsyncMock, return_value=embed) as builder,
            patch.object(v17_health.panels, "depuis_embed", return_value="panel") as formatted,
            patch.object(v17_health.panels, "envoyer", new_callable=AsyncMock) as sent,
        ):
            await cog.send_report(ctx)

        builder.assert_awaited_once_with(bot, guild, compact=True)
        formatted.assert_called_once_with(embed)
        sent.assert_awaited_once_with(ctx, "panel")


if __name__ == "__main__":
    unittest.main()
