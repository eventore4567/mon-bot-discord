"""Filtrage sécurité de la liste des serveurs du dashboard SentriX."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from web import admin_only_dashboard as access  # noqa: E402
from web import dashboard  # noqa: E402


class Guild:
    def __init__(self, guild_id: int, name: str, *, admin: bool = True):
        self.id = guild_id
        self.name = name
        self.owner_id = 999
        self.icon = None
        self.member = SimpleNamespace(
            guild_permissions=SimpleNamespace(administrator=admin, manage_guild=not admin)
        )

    def get_member(self, user_id):
        return self.member if user_id == 614 else None


class Bot:
    def __init__(self, guilds):
        self.guilds = list(guilds)
        self.by_id = {guild.id: guild for guild in guilds}

    def get_guild(self, guild_id):
        return self.by_id.get(guild_id)


class AdminGuildFilterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        access._ADMIN_MEMBER_CACHE.clear()

    async def test_only_installed_administrator_guilds_are_returned(self):
        bot = Bot([Guild(101, "Avec SentriX"), Guild(103, "Sans permission admin", admin=False)])
        session = {
            "user": {"id": "614"},
            "guilds": [
                {"id": "101", "name": "Avec SentriX", "owner": False},
                {"id": "102", "name": "Sans SentriX", "owner": True},
                {"id": "103", "name": "Sans permission admin", "owner": False},
            ],
        }
        request = SimpleNamespace(app={"bot": bot})
        gate = SimpleNamespace(_administrator_member=access._administrator_member_cached)
        self.assertTrue(await access._refresh_admin_guilds(request, gate, session))
        self.assertEqual([item["id"] for item in session["guilds"]], ["101"])
        self.assertNotIn("102", [item["id"] for item in session["guilds"]])

    async def test_newly_caught_gateway_guild_is_added_even_if_not_in_oauth_session(self):
        bot = Bot([Guild(201, "Existant"), Guild(202, "Ajouté après login")])
        session = {
            "user": {"id": "614"},
            "guilds": [{"id": "201", "name": "Existant", "owner": False}],
        }
        request = SimpleNamespace(app={"bot": bot})
        gate = SimpleNamespace(_administrator_member=access._administrator_member_cached)
        self.assertTrue(await access._refresh_admin_guilds(request, gate, session))
        self.assertEqual({item["id"] for item in session["guilds"]}, {"201", "202"})

    def test_manage_guild_without_administrator_does_not_grant_dashboard_access(self):
        guild = Guild(301, "Serveur", admin=False)
        member = guild.get_member(614)
        self.assertIsNone(dashboard._dashboard_access_level(guild, member, 614))

    def test_owner_is_allowed(self):
        guild = Guild(401, "Serveur", admin=False)
        guild.owner_id = 614
        self.assertEqual(dashboard._dashboard_access_level(guild, guild.get_member(614), 614), "owner")


if __name__ == "__main__":
    unittest.main()
