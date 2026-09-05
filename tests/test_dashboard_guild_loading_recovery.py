from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from web.dashboard_recovery_v54 import (
    _GUILD_LOADER_OLD,
    _install_guild_loading_recovery,
)


class _Bot:
    def __init__(self, ready: bool, guilds: dict[int, object] | None = None):
        self._ready = ready
        self._guilds = guilds or {}

    def is_ready(self):
        return self._ready

    def get_guild(self, guild_id: int):
        return self._guilds.get(guild_id)


class DashboardGuildLoadingRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def _dashboard(self):
        session = {
            "user": {"id": "42", "username": "Admin"},
            "guilds": [
                {"id": "2", "name": "Beta", "icon_url": None, "owner": False},
                {"id": "1", "name": "Alpha", "icon_url": None, "owner": True},
            ],
        }

        def require_session(_request):
            return session, None

        async def administrator_member(_guild, _user_id):
            return object()

        async def old_manageable(_request, _guild_id):
            return session, object(), None

        return SimpleNamespace(
            INDEX_HTML=f"<script>{_GUILD_LOADER_OLD}</script>",
            _require_session=require_session,
            _administrator_member=administrator_member,
            _manageable_guild=old_manageable,
            _invite_url=lambda _bot, guild_id=None: f"https://discord.test/invite/{guild_id}",
            _json_error=lambda message, status: SimpleNamespace(
                status=status,
                text=json.dumps({"error": message}),
            ),
        )

    @staticmethod
    def _request(bot):
        return SimpleNamespace(app={"bot": bot})

    async def test_passive_ha_returns_oauth_guilds_as_unknown_not_uninstalled(self):
        dashboard = self._dashboard()
        _install_guild_loading_recovery(dashboard)

        response = await dashboard.handle_guilds(self._request(_Bot(False)))
        payload = json.loads(response.text)

        self.assertFalse(payload["discord_ready"])
        self.assertEqual(payload["retry_after_ms"], 2000)
        self.assertEqual([g["name"] for g in payload["guilds"]], ["Alpha", "Beta"])
        self.assertTrue(all(g["installed"] is None for g in payload["guilds"]))
        self.assertTrue(all(g["invite_url"] is None for g in payload["guilds"]))

    async def test_ready_gateway_returns_real_install_state(self):
        dashboard = self._dashboard()
        _install_guild_loading_recovery(dashboard)
        installed = SimpleNamespace(id=1)

        response = await dashboard.handle_guilds(
            self._request(_Bot(True, {1: installed}))
        )
        payload = json.loads(response.text)

        self.assertTrue(payload["discord_ready"])
        self.assertIsNone(payload["retry_after_ms"])
        self.assertEqual(payload["guilds"][0]["id"], "1")
        self.assertTrue(payload["guilds"][0]["installed"])
        self.assertFalse(payload["guilds"][1]["installed"])
        self.assertEqual(
            payload["guilds"][1]["invite_url"],
            "https://discord.test/invite/2",
        )

    async def test_manageable_route_returns_503_while_gateway_is_not_ready(self):
        dashboard = self._dashboard()
        _install_guild_loading_recovery(dashboard)

        _session, guild, error = await dashboard._manageable_guild(
            self._request(_Bot(False)), 1
        )

        self.assertIsNone(guild)
        self.assertEqual(error.status, 503)
        self.assertIn("connexion à Discord", json.loads(error.text)["error"])

    def test_frontend_retries_instead_of_offering_false_invites(self):
        dashboard = self._dashboard()
        _install_guild_loading_recovery(dashboard)

        self.assertIn("Connexion Discord en cours…", dashboard.INDEX_HTML)
        self.assertIn("__sentrixGuildRetry", dashboard.INDEX_HTML)
        self.assertNotIn(_GUILD_LOADER_OLD, dashboard.INDEX_HTML)

    def test_install_is_idempotent(self):
        dashboard = self._dashboard()
        _install_guild_loading_recovery(dashboard)
        first_handler = dashboard.handle_guilds
        _install_guild_loading_recovery(dashboard)
        self.assertIs(first_handler, dashboard.handle_guilds)

    def test_partial_dashboard_namespace_is_ignored(self):
        dashboard = SimpleNamespace()
        _install_guild_loading_recovery(dashboard)
        self.assertFalse(
            getattr(dashboard, "_sentrix_guild_loading_recovery_v54", False)
        )


if __name__ == "__main__":
    unittest.main()
