"""Exercise the HTTPS boundary over real aiohttp connections and existing auth guards."""
from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from web import admin_only_dashboard, dashboard, dashboard_ha_proxy_v1, http_surfaces


DASHBOARD_ORIGIN = "https://dashboard.sentrix.test"
API_ORIGIN = "https://api.sentrix.test"
DASHBOARD_HOST = "dashboard.sentrix.test"
API_HOST = "api.sentrix.test"
SECRET = "test-proxy-secret-with-at-least-32-characters"
COOKIE = f"{dashboard.SESSION_COOKIE}=session-admin"
CSRF = "test-csrf-token"


class HttpSurfacesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        env = patch.dict("os.environ", {
            "DASHBOARD_PUBLIC_URL": DASHBOARD_ORIGIN,
            "API_PUBLIC_URL": API_ORIGIN,
            "SENTRIX_HTTP_PROXY_SECRET": SECRET,
            "SENTRIX_API_RATE_LIMIT": "120",
            "SENTRIX_API_WRITE_RATE_LIMIT": "30",
        })
        env.start()
        self.addCleanup(env.stop)
        owner = patch.object(admin_only_dashboard, "is_bot_owner_id", lambda value: str(value) == "42")
        owner.start()
        self.addCleanup(owner.stop)
        self.handled = []

    def make_app(self, *, passive=False, coordinator=None):
        member = SimpleNamespace(guild_permissions=SimpleNamespace(administrator=True))
        guild = SimpleNamespace(id=123, name="Test guild", owner_id=7, icon=None, get_member=lambda _id: member)
        bot = SimpleNamespace(guilds=[guild], get_guild=lambda _id: guild, is_ready=lambda: not passive)

        @web.middleware
        async def ha_session_hydrator(request, handler):
            session_id = request.cookies.get(dashboard.SESSION_COOKIE)
            if session_id in {"session-admin", "session-owner"}:
                request.app["sessions"][session_id] = {
                    "expires_at": time.time() + 3600,
                    "csrf": CSRF,
                    "user": {"id": "42" if session_id == "session-owner" else "7"},
                    "guilds": [],
                }
            return await handler(request)

        ha_session_hydrator._sentrix_session_hydrator = True

        async def public_page(request):
            self.handled.append(request.path)
            return web.Response(text="<html><body>Original SentriX design</body></html>", content_type="text/html")

        async def health(request):
            if request.query.get("mode") == "unready":
                raise web.HTTPServiceUnavailable(text="redis-password and bot-token must remain private")
            if request.query.get("mode") == "crash":
                raise RuntimeError("private runtime details")
            return web.json_response({"ok": True, "guilds": [123], "redis_password": "private", "leader": True})

        async def echo(request):
            self.handled.append(request.path)
            response = web.json_response({
                "ok": True,
                "body": (await request.read()).decode(),
                "cookie": request.cookies.get(dashboard.SESSION_COOKIE),
                "csrf": request.headers.get("X-CSRF-Token"),
            })
            response.set_cookie("roundtrip", "preserved", httponly=True)
            return response

        async def bad_request(_request):
            raise web.HTTPBadRequest(text="invalid request")

        async def crash(_request):
            raise RuntimeError("handler failure")

        def base_build(_bot):
            app = web.Application(middlewares=[ha_session_hydrator])
            app["bot"] = bot
            app["sessions"] = {}
            app.router.add_get("/", public_page)
            app.router.add_get("/app", public_page)
            app.router.add_get("/login", public_page)
            app.router.add_get("/oauth/callback", public_page)
            app.router.add_get("/owner-servers", public_page)
            app.router.add_get("/health", health)
            app.router.add_get("/api/public", echo)
            app.router.add_get("/api/me", echo)
            app.router.add_get("/api/guilds", echo)
            app.router.add_put("/api/guilds/{guild_id}/settings", echo)
            app.router.add_post("/logout", echo)
            app.router.add_get("/api/owner/status", echo)
            app.router.add_post("/api/runtime/slash-heartbeat", echo)
            app.router.add_get("/api/error", bad_request)
            app.router.add_get("/api/crash", crash)
            return app

        guards = SimpleNamespace(
            SESSION_COOKIE=dashboard.SESSION_COOKIE,
            _session=dashboard._session,
            _require_session=dashboard._require_session,
            _require_csrf=dashboard._require_csrf,
            _json_error=dashboard._json_error,
            _administrator_member=dashboard._administrator_member,
            build_app=base_build,
        )
        with patch.object(admin_only_dashboard, "_INSTALLED", False):
            admin_only_dashboard.install(guards)
        if coordinator is not None:
            with patch.object(dashboard_ha_proxy_v1, "_INSTALLED", False):
                dashboard_ha_proxy_v1.install(guards, coordinator)
        app = guards.build_app(bot)
        return http_surfaces.apply(app, guards)

    async def client_for(self, app):
        client = TestClient(TestServer(app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        return client

    async def request(self, client, method, path, *, host=API_HOST, headers=None, **kwargs):
        return await client.request(method, path, headers={"Host": host, **(headers or {})}, allow_redirects=False, **kwargs)

    async def test_dashboard_html_unchanged_and_api_has_no_pages_or_oauth(self):
        client = await self.client_for(self.make_app())
        response = await self.request(client, "GET", "/", host=DASHBOARD_HOST)
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.text(), "<html><body>Original SentriX design</body></html>")
        for path in ("/", "/app", "/login", "/oauth/callback", "/owner-servers"):
            with self.subTest(path=path):
                response = await self.request(client, "GET", path)
                self.assertEqual(response.status, 404)
                self.assertNotIn("Original SentriX design", await response.text())
        response = await self.request(client, "GET", "/api/public")
        self.assertEqual(response.status, 200)

    async def test_host_boundary_ignores_untrusted_forwarded_host(self):
        client = await self.client_for(self.make_app())
        response = await self.request(client, "GET", "/login", headers={"X-Forwarded-Host": DASHBOARD_HOST})
        self.assertEqual(response.status, 404)
        response = await self.request(client, "GET", "/api/public", host="attacker.example", headers={"X-Forwarded-Host": API_HOST})
        self.assertIn(response.status, {400, 403, 404, 421})
        response = await self.request(client, "GET", "/", host=DASHBOARD_HOST, headers={"X-Forwarded-Host": "attacker.example"})
        self.assertEqual(response.status, 200)

    async def test_health_is_minimal_for_both_hosts_and_healthcheck_host(self):
        client = await self.client_for(self.make_app())
        for host in (DASHBOARD_HOST, API_HOST, "healthcheck.railway.app"):
            for suffix, status in (("", 200), ("?mode=unready", 503), ("?mode=crash", 500)):
                with self.subTest(host=host, suffix=suffix):
                    response = await self.request(client, "GET", "/health" + suffix, host=host)
                    self.assertEqual(response.status, status)
                    payload = await response.json()
                    self.assertEqual(set(payload), {"ok", "surface"})
                    self.assertEqual(payload["ok"], status == 200)
                    self.assertNotIn("private", await response.text())
        response = await self.request(client, "HEAD", "/health")
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.read(), b"")

    async def test_strict_cors_on_success_auth_and_handler_errors(self):
        client = await self.client_for(self.make_app())
        cases = [("/api/public", {}, 200), ("/api/guilds", {}, 401),
                 ("/api/error", {"Cookie": COOKIE}, 400), ("/api/crash", {"Cookie": COOKIE}, 500)]
        for path, headers, status in cases:
            with self.subTest(path=path):
                response = await self.request(client, "GET", path, headers={"Origin": DASHBOARD_ORIGIN, **headers})
                self.assertEqual(response.status, status)
                self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), DASHBOARD_ORIGIN)
                self.assertEqual(response.headers.get("Access-Control-Allow-Credentials"), "true")
                self.assertIn("origin", response.headers.get("Vary", "").lower())
        for origin in ("https://evil.test", "null", DASHBOARD_ORIGIN + ".evil.test", "http://dashboard.sentrix.test"):
            with self.subTest(origin=origin):
                response = await self.request(client, "GET", "/api/public", headers={"Origin": origin})
                self.assertEqual(response.status, 403)
                self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        response = await self.request(client, "GET", "/api/public")
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    async def test_preflight_checks_registered_method_and_requested_headers(self):
        client = await self.client_for(self.make_app())
        valid = {"Origin": DASHBOARD_ORIGIN, "Access-Control-Request-Method": "PUT", "Access-Control-Request-Headers": "content-type, x-csrf-token"}
        response = await self.request(client, "OPTIONS", "/api/guilds/123/settings", headers=valid)
        self.assertIn(response.status, {200, 204})
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), DASHBOARD_ORIGIN)
        self.assertIn("PUT", response.headers.get("Access-Control-Allow-Methods", ""))
        self.assertIn("x-csrf-token", response.headers.get("Access-Control-Allow-Headers", "").lower())
        for path, overrides in (
            ("/api/guilds/123/settings", {"Access-Control-Request-Method": "DELETE"}),
            ("/api/guilds/123/settings", {"Access-Control-Request-Headers": "x-untrusted-header"}),
            ("/api/unknown", {}),
            ("/api/runtime/slash-heartbeat", {"Access-Control-Request-Method": "POST"}),
            ("/api/guilds/123/settings", {"Origin": "https://evil.test"}),
        ):
            with self.subTest(path=path, overrides=overrides):
                response = await self.request(client, "OPTIONS", path, headers={**valid, **overrides})
                self.assertIn(response.status, {400, 403, 404, 405})

    async def test_real_session_and_csrf_guards_run_after_session_hydration(self):
        app = self.make_app()
        client = await self.client_for(app)
        self.assertEqual(app["sessions"], {})
        response = await self.request(client, "GET", "/api/me")
        self.assertEqual(response.status, 401)
        response = await self.request(client, "GET", "/api/me", headers={"Cookie": COOKIE})
        self.assertEqual(response.status, 200)
        self.assertIn("session-admin", app["sessions"])
        for token, status in ((None, 403), ("wrong", 403), (CSRF, 200)):
            headers = {"Cookie": COOKIE, "Origin": DASHBOARD_ORIGIN}
            if token is not None:
                headers["X-CSRF-Token"] = token
            response = await self.request(client, "PUT", "/api/guilds/123/settings", headers=headers, json={"prefix": "!"})
            self.assertEqual(response.status, status)
        response = await self.request(client, "PUT", "/api/guilds/123/settings", headers={"X-CSRF-Token": CSRF})
        self.assertEqual(response.status, 401)

    async def test_dashboard_mutations_and_logout_keep_csrf(self):
        client = await self.client_for(self.make_app())
        for method, path in (("PUT", "/api/guilds/123/settings"), ("POST", "/logout")):
            response = await self.request(client, method, path, host=DASHBOARD_HOST, headers={"Cookie": COOKIE})
            self.assertEqual(response.status, 403)
            response = await self.request(client, method, path, host=DASHBOARD_HOST, headers={"Cookie": COOKIE, "X-CSRF-Token": CSRF})
            self.assertEqual(response.status, 200)

    async def test_runtime_unknown_and_owner_routes_stay_private(self):
        client = await self.client_for(self.make_app())
        owner_cookie = f"{dashboard.SESSION_COOKIE}=session-owner"
        for host in (DASHBOARD_HOST, API_HOST):
            for method, path in (("POST", "/api/runtime/slash-heartbeat"), ("GET", "/api/runtime/secret"), ("GET", "/api/internal/secrets"), ("GET", "/metrics"), ("GET", "/debug")):
                with self.subTest(host=host, path=path):
                    response = await self.request(client, method, path, host=host, headers={"Cookie": owner_cookie, "X-CSRF-Token": CSRF})
                    self.assertEqual(response.status, 404)
        response = await self.request(client, "GET", "/api/owner/status", host=DASHBOARD_HOST)
        self.assertEqual(response.status, 401)
        response = await self.request(client, "GET", "/api/owner/status", host=DASHBOARD_HOST, headers={"Cookie": COOKIE})
        self.assertEqual(response.status, 404)
        response = await self.request(client, "GET", "/api/owner/status", host=DASHBOARD_HOST, headers={"Cookie": owner_cookie})
        self.assertEqual(response.status, 200)
        response = await self.request(client, "GET", "/api/owner/status", headers={"Cookie": owner_cookie})
        self.assertEqual(response.status, 404)
        self.assertNotIn("/api/runtime/slash-heartbeat", self.handled)

    async def test_api_rate_limit_cannot_be_bypassed_with_forwarded_ip(self):
        with patch.dict("os.environ", {"SENTRIX_API_RATE_LIMIT": "3"}):
            client = await self.client_for(self.make_app())
        for index in range(3):
            response = await self.request(client, "GET", "/api/public", headers={"X-Forwarded-For": f"198.51.100.{index}", "X-Real-IP": f"203.0.113.{index}"})
            self.assertEqual(response.status, 200)
        response = await self.request(client, "GET", "/api/public", headers={"X-Forwarded-For": "192.0.2.99", "X-Real-IP": "192.0.2.99", "Origin": DASHBOARD_ORIGIN})
        self.assertEqual(response.status, 429)
        self.assertTrue(response.headers.get("Retry-After"))
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), DASHBOARD_ORIGIN)
        response = await self.request(client, "GET", "/health")
        self.assertEqual(response.status, 200)

    async def test_write_rate_limit_is_separate_and_also_covers_dashboard_api(self):
        with patch.dict("os.environ", {"SENTRIX_API_WRITE_RATE_LIMIT": "2"}):
            client = await self.client_for(self.make_app())
        headers = {"Cookie": COOKIE, "X-CSRF-Token": CSRF}
        for _ in range(2):
            response = await self.request(client, "PUT", "/api/guilds/123/settings", host=DASHBOARD_HOST, headers=headers)
            self.assertEqual(response.status, 200)
        response = await self.request(client, "PUT", "/api/guilds/123/settings", host=DASHBOARD_HOST, headers=headers)
        self.assertEqual(response.status, 429)
        response = await self.request(client, "GET", "/api/public", host=DASHBOARD_HOST)
        self.assertEqual(response.status, 200)

    def signed_headers(self, app, *, method="PUT", path="/api/guilds/123/settings", body=b"{}", cookie=COOKIE):
        request = make_mocked_request(method, path, app=app, headers={
            "Host": API_HOST, "Cookie": cookie, "X-CSRF-Token": CSRF,
            "Content-Type": "application/json", "Origin": DASHBOARD_ORIGIN,
        })
        headers = http_surfaces.sign_proxy_headers(request, {}, body)
        return {"Host": "mon-bot-discord.railway.internal:8080", **headers}

    async def test_signed_internal_hop_preserves_auth_and_rejects_replay_and_tampering(self):
        app = self.make_app()
        client = await self.client_for(app)
        path = "/api/guilds/123/settings"
        headers = self.signed_headers(app)
        response = await client.put(path, data=b"{}", headers=headers)
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["csrf"], CSRF)
        response = await client.put(path, data=b"{}", headers=headers)
        self.assertEqual(response.status, 403)
        for field, value in (("Cookie", "forged"), ("X-CSRF-Token", "forged"),
                             ("Origin", "https://evil.test"), ("X-SentriX-Proxy-Host", DASHBOARD_HOST),
                             ("X-SentriX-Proxy-Client", "forged"), ("X-SentriX-Proxy-Signature", "invalid")):
            fresh = self.signed_headers(app)
            fresh[field] = value
            response = await client.put(path, data=b"{}", headers=fresh)
            self.assertEqual(response.status, 403, field)
        response = await client.put(path, data=b'{"changed":true}', headers=self.signed_headers(app))
        self.assertEqual(response.status, 403)
        response = await client.put(path + "?changed=1", data=b"{}", headers=self.signed_headers(app))
        self.assertEqual(response.status, 403)
        with patch.object(http_surfaces.time, "time", return_value=time.time() - 120):
            old = self.signed_headers(app)
        response = await client.put(path, data=b"{}", headers=old)
        self.assertEqual(response.status, 403)
        for headers in ({"X-SentriX-HA-Proxy": "1"}, {"X-SentriX-Proxy-Host": API_HOST}):
            response = await self.request(client, "GET", "/api/public", headers=headers)
            self.assertEqual(response.status, 403)
        signed = self.signed_headers(app)
        signed["Host"] = API_HOST
        response = await client.put(path, data=b"{}", headers=signed)
        self.assertEqual(response.status, 403)

    async def test_real_ha_proxy_authenticates_hop_and_preserves_cookies(self):
        leader = await self.client_for(self.make_app())
        coordinator = SimpleNamespace(enabled=True, is_leader=False, role="standby", state="standby")
        follower_app = self.make_app(passive=True, coordinator=coordinator)
        follower = await self.client_for(follower_app)
        with patch.object(dashboard_ha_proxy_v1, "_peer_base_url", return_value=str(leader.make_url("/")).rstrip("/")):
            response = await self.request(follower, "PUT", "/api/guilds/123/settings", headers={
                "Cookie": COOKIE, "X-CSRF-Token": CSRF, "Origin": DASHBOARD_ORIGIN,
            }, data=b"{}")
            self.assertEqual(response.status, 200, await response.text())
            body = await response.json()
            self.assertEqual(body["cookie"], "session-admin")
            self.assertEqual(body["csrf"], CSRF)
            self.assertIn("roundtrip=preserved", response.headers.get("Set-Cookie", ""))
            response = await self.request(follower, "GET", "/api/me")
            self.assertEqual(response.status, 401)
            response = await self.request(follower, "GET", "/login")
            self.assertEqual(response.status, 404)
        # A verified hop to another passive process cannot bounce indefinitely.
        follower.session.cookie_jar.clear()
        headers = self.signed_headers(follower_app, method="GET", path="/api/me", body=b"")
        response = await follower.get("/api/me", headers=headers)
        self.assertEqual(response.status, 503)

    async def test_secret_only_rollout_signs_before_hostname_split_is_enabled(self):
        with patch.dict("os.environ", {"API_PUBLIC_URL": ""}):
            app = self.make_app()
            client = await self.client_for(app)
            headers = self.signed_headers(app, method="GET", path="/api/me", body=b"")
            self.assertIn("X-SentriX-Proxy-Signature", headers)
            response = await client.get("/api/me", headers=headers)
            self.assertEqual(response.status, 200)
            response = await self.request(client, "GET", "/", host=API_HOST)
            self.assertEqual(response.status, 200)

    def test_health_preserves_companion_contract_and_removes_error_details(self):
        response = web.json_response({
            "ok": True, "discord_ready": False, "latency_ms": None,
            "failover": {"enabled": True, "leader": False, "role": "standby", "state": "standby",
                         "ttl_seconds": 30, "leader_for_seconds": 0, "error": "redis://user:password@internal",
                         "private_address": "internal"}, "secret": "hidden",
        })
        health = http_surfaces._health_payload(response, 200, "api")
        self.assertFalse(health["discord_ready"])
        self.assertTrue(health["failover"]["enabled"])
        self.assertFalse(health["failover"]["leader"])
        self.assertEqual(health["failover"]["role"], "standby")
        self.assertEqual(health["failover"]["error"], "unavailable")
        self.assertNotIn("password", str(health))
        self.assertNotIn("private_address", health["failover"])
        self.assertNotIn("secret", health)

    def test_configuration_fails_closed_and_apply_is_idempotent(self):
        for overrides in (
            {"DASHBOARD_PUBLIC_URL": API_ORIGIN},
            {"DASHBOARD_PUBLIC_URL": "http://dashboard.sentrix.test"},
            {"API_PUBLIC_URL": "http://api.sentrix.test"},
            {"API_PUBLIC_URL": API_ORIGIN + "/unexpected"},
            {"DASHBOARD_PUBLIC_URL": ""},
            {"SENTRIX_HTTP_PROXY_SECRET": ""},
            {"SENTRIX_HTTP_PROXY_SECRET": "too-short"},
        ):
            with self.subTest(overrides=overrides), patch.dict("os.environ", overrides):
                with self.assertRaises((ValueError, RuntimeError)):
                    self.make_app()
        app = self.make_app()
        before = list(app.middlewares)
        self.assertIs(http_surfaces.apply(app, dashboard), app)
        self.assertEqual(list(app.middlewares), before)


if __name__ == "__main__":
    unittest.main()
