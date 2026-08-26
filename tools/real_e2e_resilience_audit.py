#!/usr/bin/env python3
"""Gate E2E synthétique + résilience pour SentriX.

Ce test ne simule jamais un compte utilisateur Discord et ne prétend pas être un clic réel
sur Discord. Il couvre ce que CI peut prouver sans self-bot : boot complet des cogs,
parcours HTTP du dashboard, dégradation/reprise PostgreSQL+Redis optionnels et panne OpenAI
sans fuite d'erreur technique vers l'utilisateur.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")


class _DummyAvatar:
    url = "https://cdn.discordapp.com/embed/avatars/0.png"


class _DummyUser:
    id = 424242
    name = "SentriX"
    display_avatar = _DummyAvatar()


class _DummyBot:
    def __init__(self) -> None:
        self.user = _DummyUser()
        self.guilds = []
        self.latency = 0.042
        self._ready = False
        self.db = None
        self._listeners = []

    def is_ready(self) -> bool:
        return self._ready

    def get_guild(self, guild_id: int):
        return None

    def add_listener(self, callback, name: str | None = None) -> None:
        self._listeners.append((name or getattr(callback, "__name__", "listener"), callback))

    def get_command(self, name: str):
        return None

    def add_command(self, command) -> None:
        return None

    async def wait_until_ready(self) -> None:
        return None

    def is_closed(self) -> bool:
        # Les boucles de fond installées par certains modules ne doivent pas tourner
        # pendant le parcours HTTP synthétique : elles sont couvertes par le boot runtime.
        return True


async def dashboard_http_journey() -> int:
    """Teste le dashboard via un vrai serveur HTTP aiohttp local + SQLite réel."""
    from aiohttp.test_utils import TestClient, TestServer

    import config
    import web as sentrix_web  # noqa: F401 - active les installateurs du package web
    from database.db import Database
    from web import dashboard

    old_secret = config.DISCORD_CLIENT_SECRET
    config.DISCORD_CLIENT_SECRET = ""
    checks = 0
    with tempfile.TemporaryDirectory(prefix="sentrix-dashboard-http-") as folder:
        db = Database(str(pathlib.Path(folder) / "dashboard.db"))
        await db.connect()
        bot = _DummyBot()
        bot.db = db
        client = TestClient(TestServer(dashboard.build_app(bot)))
        try:
            await client.start_server()

            response = await client.get("/health")
            assert response.status == 200
            data = await response.json()
            assert data.get("discord_ready") is False, f"health inattendu hors connexion: {data}"
            assert data.get("latency_ms") is None
            assert response.headers["X-Frame-Options"] == "DENY"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            checks += 1

            response = await client.get("/api/public")
            assert response.status == 200
            data = await response.json()
            assert data["bot_name"] == "SentriX"
            assert data["online"] is False and data["guilds"] == 0
            assert data["oauth_ready"] is False
            assert "no-store" in response.headers.get("Cache-Control", "")
            checks += 1

            response = await client.get("/app")
            assert response.status == 200
            html = await response.text()
            assert 'id="sentrix-core-recovery"' in html
            assert "Mode simple" in html and "Mode avancé" in html
            assert "loginButton" in html
            assert "no-store" in response.headers.get("Cache-Control", "")
            checks += 1

            for path in ("/api/me", "/api/guilds", "/api/guilds/123456"):
                response = await client.get(path)
                assert response.status == 401, f"{path}: attendu 401, reçu {response.status}"
                payload = await response.json()
                assert payload.get("ok") is False
                checks += 1

            response = await client.get("/login", allow_redirects=False)
            assert response.status in {302, 303}
            assert response.headers.get("Location") == "/?auth=missing"
            checks += 1

            bot._ready = True
            response = await client.get("/health")
            data = await response.json()
            assert data.get("discord_ready") is True, f"health inattendu prêt: {data}"
            assert data.get("latency_ms") == 42
            checks += 1

            response = await client.get("/api/public")
            data = await response.json()
            assert data["online"] is True and data["latency_ms"] == 42
            checks += 1
        finally:
            await client.close()
            await db.close()
            config.DISCORD_CLIENT_SECRET = old_secret
    return checks


class _FailingAsyncpg:
    @staticmethod
    async def create_pool(*args, **kwargs):
        raise OSError("synthetic postgres outage")


class _FailingRedisClient:
    async def ping(self):
        raise OSError("synthetic redis outage")


class _FailingRedisModule:
    @staticmethod
    def from_url(*args, **kwargs):
        return _FailingRedisClient()


class _GoodPgConnection:
    async def execute(self, *args, **kwargs):
        return "OK"


class _AcquireContext:
    async def __aenter__(self):
        return _GoodPgConnection()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _GoodPgPool:
    def acquire(self):
        return _AcquireContext()

    async def fetchval(self, *args, **kwargs):
        return 1

    async def execute(self, *args, **kwargs):
        return "OK"

    async def close(self):
        return None


class _GoodAsyncpg:
    @staticmethod
    async def create_pool(*args, **kwargs):
        return _GoodPgPool()


class _GoodRedisClient:
    async def ping(self):
        return True

    async def aclose(self):
        return None

    async def get(self, key):
        return "0"

    async def set(self, *args, **kwargs):
        return True

    async def publish(self, *args, **kwargs):
        return 1

    async def eval(self, *args, **kwargs):
        return 1


class _GoodRedisModule:
    @staticmethod
    def from_url(*args, **kwargs):
        return _GoodRedisClient()


async def infrastructure_chaos_journey() -> int:
    """Prouve qu'une panne PG/Redis optionnelle ne casse pas SentriX et qu'un reconnect marche."""
    import utils.enterprise_infra as infra_module

    old_pg = infra_module.asyncpg
    old_redis = infra_module.redis_async
    old_pg_url = os.environ.get("POSTGRES_URL")
    old_redis_url = os.environ.get("REDIS_URL")
    os.environ["POSTGRES_URL"] = "postgresql://synthetic.invalid/sentrix"
    os.environ["REDIS_URL"] = "redis://synthetic.invalid/0"
    checks = 0
    try:
        infra_module.asyncpg = _FailingAsyncpg
        infra_module.redis_async = _FailingRedisModule
        infra = infra_module.EnterpriseInfra()
        await infra.connect()
        assert infra.pg_pool is None and infra.redis is None
        assert infra.postgres_error and infra.redis_error
        degraded = await infra.health()
        assert degraded["postgres_configured"] is True and degraded["postgres_online"] is False
        assert degraded["redis_configured"] is True and degraded["redis_online"] is False
        assert await infra.incr("synthetic") is None
        assert await infra.get_counter("synthetic") is None
        assert await infra.acquire_lease("synthetic", "owner") is True
        await infra.release_lease("synthetic", "owner")
        await infra.publish("synthetic", {"ok": True})
        await infra.mirror_event("synthetic", None, {"ok": True}, 1)
        await infra.mirror_metric("synthetic", None, 1.0, {}, 1)
        checks += 1

        infra_module.asyncpg = _GoodAsyncpg
        infra_module.redis_async = _GoodRedisModule
        await infra.reconnect()
        recovered = await infra.health()
        assert recovered["postgres_online"] is True
        assert recovered["redis_online"] is True
        assert recovered["postgres_error"] is None and recovered["redis_error"] is None
        assert await infra.get_counter("synthetic") == 0
        assert await infra.acquire_lease("synthetic", "owner") is True
        await infra.publish("synthetic", {"recovered": True})
        await infra.mirror_event("synthetic", None, {"recovered": True}, 2)
        await infra.mirror_metric("synthetic", None, 2.0, {}, 2)
        await infra.close()
        checks += 1
    finally:
        infra_module.asyncpg = old_pg
        infra_module.redis_async = old_redis
        if old_pg_url is None:
            os.environ.pop("POSTGRES_URL", None)
        else:
            os.environ["POSTGRES_URL"] = old_pg_url
        if old_redis_url is None:
            os.environ.pop("REDIS_URL", None)
        else:
            os.environ["REDIS_URL"] = old_redis_url
    return checks


class _BrokenResponses:
    async def create(self, **kwargs):
        raise RuntimeError("synthetic-secret-detail-must-not-reach-user")


class _BrokenOpenAIClient:
    responses = _BrokenResponses()


async def ai_outage_journey() -> int:
    """Une panne IA doit devenir un code générique sûr, jamais une exception utilisateur."""
    from utils import ai_service

    old_get_client = ai_service.get_client
    checks = 0
    try:
        ai_service.get_client = lambda: None
        missing = await ai_service.generate("bonjour")
        assert missing.error == ai_service.ERROR_NO_KEY
        checks += 1

        ai_service.get_client = lambda: _BrokenOpenAIClient()
        broken = await ai_service.generate("bonjour", model_key=ai_service.MODEL_LUNA)
        assert broken.error == ai_service.ERROR_GENERIC
        public_message = ai_service.error_message(broken.error)
        assert "synthetic-secret-detail" not in public_message
        assert "momentanément indisponible" in public_message
        assert ai_service.REQUEST_TIMEOUT_SECONDS <= 20.0
        checks += 1
    finally:
        ai_service.get_client = old_get_client
    return checks


async def full_runtime_journey(folder: pathlib.Path) -> int:
    """Réutilise la gate d'acceptation pour charger le runtime complet sans connexion Discord."""
    from tools.user_acceptance_audit import runtime_journey

    metrics = await runtime_journey(str(folder / "real-e2e-runtime.db"))
    assert int(metrics["extensions"]) > 0
    assert int(metrics["commands"]) > 0
    # La surface V3 utilise volontairement le plafond Discord complet : 100 racines slash.
    assert int(metrics["slash_roots"]) <= 100
    return 1


async def main_audit() -> None:
    with tempfile.TemporaryDirectory(prefix="sentrix-real-e2e-") as folder:
        root = pathlib.Path(folder)
        dashboard_checks = await dashboard_http_journey()
        infra_checks = await infrastructure_chaos_journey()
        ai_checks = await ai_outage_journey()
        runtime_checks = await full_runtime_journey(root)

    total = dashboard_checks + infra_checks + ai_checks + runtime_checks
    print(
        "Synthetic E2E + resilience: "
        f"dashboard={dashboard_checks}, infra={infra_checks}, ai={ai_checks}, runtime={runtime_checks}, total={total}"
    )
    print(
        "OK: dashboard HTTP, auth fail-closed, boot complet, panne/reprise PostgreSQL+Redis "
        "et panne OpenAI validés sans connexion utilisateur Discord automatisée"
    )


if __name__ == "__main__":
    asyncio.run(main_audit())
