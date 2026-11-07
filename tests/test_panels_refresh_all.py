"""Safety and scope tests for the SentriX owner-only global panel refresh."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.panels_refresh import PanelsRefresh


class PanelRefreshScopeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.a = SimpleNamespace(id=10)
        self.b = SimpleNamespace(id=20)
        self.guilds = {10: self.a, 20: self.b}
        self.bot = SimpleNamespace(
            db=SimpleNamespace(fetchall=AsyncMock()),
            get_guild=lambda guild_id: self.guilds.get(guild_id),
        )
        self.cog = PanelsRefresh(self.bot)
        self.ctx = SimpleNamespace(guild=self.a, send=AsyncMock())

    async def _execute(self, mode):
        with (
            patch("cogs.panels_refresh.sx_panels.envoyer", new_callable=AsyncMock) as send,
            patch("cogs.panels_refresh.sx_panels.depuis_embed") as convert,
            patch("cogs.panels_refresh.embeds.neutral") as embed,
            patch("cogs.panels_refresh.asyncio.sleep", new_callable=AsyncMock),
        ):
            await PanelsRefresh.restart.callback(self.cog, self.ctx, mode)
            return send

    async def test_global_runs_all_cached_guilds_and_skips_unavailable(self):
        self.bot.db.fetchall.return_value = [
            {"guild_id": 10}, {"guild_id": 20}, {"guild_id": 30}
        ]
        self.cog.refresh_guild = AsyncMock(
            side_effect=lambda guild, **kwargs: self._result(guild, **kwargs)
        )
        await self._execute("all")
        seen = [
            (call.args[0].id, call.kwargs["published_only"])
            for call in self.cog.refresh_guild.await_args_list
        ]
        self.assertEqual(seen, [(10, True), (20, True)])
        self.assertFalse(self.cog._global_running)
        self.bot.db.fetchall.assert_awaited_once()
        self.assertIn("message_id IS NOT NULL", self.bot.db.fetchall.await_args.args[0])

    async def _result(self, guild, **kwargs):
        result = self.cog._new_stats()
        result["updated"] = 1
        return result, [], 1

    async def test_default_scope_only_invoking_server(self):
        self.cog.refresh_guild = AsyncMock(side_effect=self._result)
        await self._execute("server")
        self.cog.refresh_guild.assert_awaited_once_with(
            self.a, published_only=False
        )
        self.bot.db.fetchall.assert_not_awaited()
        self.assertEqual(self.cog._running_guilds, set())

    async def test_invalid_scope_is_rejected_without_rebuilding(self):
        self.cog.refresh_guild = AsyncMock()
        await self._execute("whatever")
        self.cog.refresh_guild.assert_not_awaited()
        self.ctx.send.assert_awaited_once()

    async def test_concurrent_global_calls_are_denied(self):
        self.cog._global_running = True
        self.cog.refresh_guild = AsyncMock()
        await self._execute("all")
        self.cog.refresh_guild.assert_not_awaited()
        self.ctx.send.assert_awaited_once()

    async def test_refresh_guild_reads_only_its_own_panels(self):
        self.bot.db.fetchall.return_value = [
            {"id": 7, "guild_id": 10, "name": "Support"}
        ]
        self.cog.refresh_one = AsyncMock(return_value=("updated", None))
        with patch("cogs.panels_refresh.asyncio.sleep", new_callable=AsyncMock):
            totals, errors, count = await self.cog.refresh_guild(
                self.a, published_only=True
            )
        self.assertEqual((count, totals["updated"], errors), (1, 1, []))
        self.bot.db.fetchall.assert_awaited_once_with(
            "SELECT * FROM ticket_panels_v2 WHERE guild_id=?"
            " AND message_id IS NOT NULL ORDER BY id",
            (10,),
        )
        self.cog.refresh_one.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
