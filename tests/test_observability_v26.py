from __future__ import annotations

import asyncio
import types
import unittest

from cogs import runtime_observability_v26 as obs


class FakeDB:
    async def execute(self, query, params=()):
        await asyncio.sleep(0)
        return "ok"

    async def fetchone(self, query, params=()):
        await asyncio.sleep(0)
        return {"ok": 1}

    async def fetchall(self, query, params=()):
        await asyncio.sleep(0)
        return []


class FakeBot:
    def __init__(self):
        self.db = FakeDB()
        self.listeners = []

    def add_listener(self, callback, name=None):
        self.listeners.append((name, callback))


class ObservabilityV26Tests(unittest.IsolatedAsyncioTestCase):
    async def test_db_calls_are_measured_without_parameters(self):
        bot = FakeBot()
        obs.install(bot)
        await bot.db.fetchone("SELECT cash FROM economy WHERE guild_id=? AND user_id=?", (123, 456))
        await bot.db.fetchall("SELECT * FROM warnings WHERE guild_id=?", (123,))
        snap = obs.snapshot(bot)
        self.assertEqual(snap["db_calls"], 2)
        self.assertGreaterEqual(snap["db_avg_ms"], 0)
        # Les paramètres 123/456 ne sont jamais conservés dans la télémétrie.
        raw = repr(bot._sentrix_observability_v26)
        self.assertNotIn("(123, 456)", raw)

    async def test_install_is_idempotent(self):
        bot = FakeBot()
        obs.install(bot)
        first_listener_count = len(bot.listeners)
        obs.install(bot)
        self.assertEqual(len(bot.listeners), first_listener_count)
        await bot.db.execute("SELECT 1")
        self.assertEqual(obs.snapshot(bot)["db_calls"], 1)

    async def test_error_keeps_type_not_message(self):
        bot = FakeBot()
        obs.install(bot)
        error = RuntimeError("mot-de-passe-ultra-secret")
        obs.record_error(
            bot,
            command="test",
            error=error,
            guild_id=1,
            user_id=2,
            reference=3,
        )
        snap = obs.snapshot(bot)
        self.assertEqual(snap["last_error"]["type"], "RuntimeError")
        self.assertNotIn("mot-de-passe-ultra-secret", repr(bot._sentrix_observability_v26))

    def test_query_fingerprint_does_not_need_parameters(self):
        value = obs._query_fingerprint("  SELECT   *  FROM economy  WHERE user_id = ?  ")
        self.assertEqual(value, "SELECT * FROM economy WHERE user_id = ?")


if __name__ == "__main__":
    unittest.main()
