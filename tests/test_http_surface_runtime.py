"""Fallback startup and bot telemetry must respect the public HTTP boundary."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from cogs import slash_reliability_v7 as runtime
from web import dashboard, dashboard_recovery_v54 as recovery, http_surfaces


ENV = {
    "DASHBOARD_PUBLIC_URL": "https://dashboard.sentrix.test",
    "API_PUBLIC_URL": "https://api.sentrix.test",
    "SENTRIX_HTTP_PROXY_SECRET": "test-secret-only-at-least-thirty-two-characters",
}


def test_ha_telemetry_stays_in_process_without_public_http():
    app = {"slash_runtime_relays": {}}
    bot = SimpleNamespace(user=SimpleNamespace(id=123), _sentrix_dashboard_runner_v54=SimpleNamespace(app=app))
    with patch.dict("os.environ", ENV), patch.object(runtime, "ClientSession", side_effect=AssertionError("Public HTTP is forbidden")):
        asyncio.run(runtime._publish_runtime_relay(bot))
    assert len(app["slash_runtime_relays"]) == 1
    item = next(iter(app["slash_runtime_relays"].values()))
    assert item["bot_user_id"] == "123"
    assert item["received_at"] > 0
    assert bot.slash_reliability_v7_state["last_publish_error"] is None


def test_telemetry_without_dashboard_fails_soft_without_public_http():
    bot = SimpleNamespace(user=None)
    with patch.dict("os.environ", ENV), patch.object(runtime, "ClientSession", side_effect=AssertionError("Public HTTP is forbidden")):
        asyncio.run(runtime._publish_runtime_relay(bot))
    assert bot.slash_reliability_v7_state["last_publish_error"] == "RuntimeError"


def test_recovery_fallback_is_guarded_and_bad_config_cannot_start_http():
    captured = []

    class Runner:
        def __init__(self, app):
            self.app = app
            captured.append(app)

        async def setup(self):
            pass

        async def cleanup(self):
            pass

    class Site:
        def __init__(self, *args):
            pass

        async def start(self):
            pass

    async def scenario():
        fake = SimpleNamespace(**{name: getattr(dashboard, name) for name in (
            "SESSION_COOKIE", "_session", "_require_session", "_require_csrf",
            "handle_index", "handle_health", "handle_login", "handle_callback", "handle_logout",
            "handle_public", "handle_me", "handle_guilds", "handle_guild", "handle_update_guild",
            "handle_welcome_get", "handle_welcome_put", "handle_welcome_test",
            "handle_create_social_notification", "handle_delete_social_notification", "handle_sanctions",
            "handle_sanction_action", "security_headers",
        )})
        fake.build_app = lambda bot: (_ for _ in ()).throw(RuntimeError("Broken optional plugin"))
        fake.start_dashboard = AsyncMock()
        fake._oauth_ready = lambda bot: True
        # Recovery's unrelated guild-loading hook expects the full real dashboard.
        with patch.object(recovery, "_install_guild_loading_recovery"), patch.object(recovery, "configure_public_url", return_value=ENV["DASHBOARD_PUBLIC_URL"]):
            recovery.install(fake)
        with patch.object(recovery.web, "AppRunner", Runner), patch.object(recovery.web, "TCPSite", Site):
            bot = SimpleNamespace()
            await fake.start_dashboard(bot)
            assert bot._sentrix_dashboard_mode_v54 == "secours"
            assert getattr(captured[-1].middlewares[0], "_sentrix_http_boundary", False)
            with patch.dict("os.environ", {"SENTRIX_HTTP_PROXY_SECRET": "invalid"}), patch.object(recovery.asyncio, "sleep", new=AsyncMock()):
                bad_bot = SimpleNamespace()
                await fake.start_dashboard(bad_bot)
                assert not hasattr(bad_bot, "_sentrix_dashboard_runner_v54")
                assert len(captured) == 1

        async with TestClient(TestServer(captured[0])) as client:
            response = await client.get("/login", headers={"Host": "api.sentrix.test"}, allow_redirects=False)
            assert response.status == 404
            response = await client.get("/api/me", headers={"Host": "api.sentrix.test"})
            assert response.status == 401
            response = await client.post("/api/runtime/slash-heartbeat", headers={"Host": "dashboard.sentrix.test"})
            assert response.status == 404

    with patch.dict("os.environ", ENV):
        asyncio.run(scenario())
