import asyncio
import json
from types import SimpleNamespace

from aiohttp import web

from web import dashboard_recovery_v54


def _dashboard_fixture(*, session_guilds, administrator_member):
    async def original_manageable(_request, _guild_id):
        return None, None, None

    async def original_handle_guilds(_request):
        return web.json_response({"guilds": []})

    async def original_metrics(_db, _guild_id):
        return {
            "warnings": 0,
            "open_tickets": 0,
            "profiles": 0,
            "economy_accounts": 0,
            "commands_24h": 0,
        }

    return SimpleNamespace(
        _manageable_guild=original_manageable,
        handle_guilds=original_handle_guilds,
        _require_session=lambda _request: (
            {"user": {"id": "42"}, "guilds": list(session_guilds)},
            None,
        ),
        _administrator_member=administrator_member,
        _invite_url=lambda _bot, guild_id=None: f"https://invite/{guild_id}",
        _json_error=lambda message, status: web.json_response(
            {"ok": False, "error": message}, status=status
        ),
        _guild_metrics=original_metrics,
        now=lambda: 10_000,
        INDEX_HTML="<html><head></head><body></body></html>",
    )


def test_guild_permission_checks_run_concurrently_without_skipping_security():
    active = 0
    max_active = 0

    async def administrator_member(guild, _user_id):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.015)
        active -= 1
        # Guild 3 simulates a server where the OAuth session is stale and current
        # Administrator permission has since been removed. It must stay hidden.
        return None if guild.id == 3 else object()

    session_guilds = [
        {"id": str(index), "name": f"Serveur {index}", "icon_url": None, "owner": False}
        for index in range(1, 7)
    ]
    dashboard = _dashboard_fixture(
        session_guilds=session_guilds,
        administrator_member=administrator_member,
    )
    dashboard_recovery_v54._install_guild_loading_recovery(dashboard)

    installed = {index: SimpleNamespace(id=index) for index in range(1, 7)}
    bot = SimpleNamespace(
        is_ready=lambda: True,
        get_guild=lambda guild_id: installed.get(guild_id),
    )
    request = SimpleNamespace(app={"bot": bot})

    response = asyncio.run(dashboard.handle_guilds(request))
    payload = json.loads(response.text)

    assert response.status == 200
    assert response.headers["Server-Timing"].startswith("guilds;dur=")
    assert max_active > 1
    assert [guild["id"] for guild in payload["guilds"]] == ["1", "2", "4", "5", "6"]
    assert all(guild["installed"] is True for guild in payload["guilds"])


def test_guild_metrics_use_one_sql_round_trip_when_schema_is_complete():
    async def administrator_member(_guild, _user_id):
        return object()

    dashboard = _dashboard_fixture(
        session_guilds=[],
        administrator_member=administrator_member,
    )
    dashboard_recovery_v54._install_guild_loading_recovery(dashboard)

    class FakeDB:
        def __init__(self):
            self.calls = []

        async def fetchone(self, query, params):
            self.calls.append((query, params))
            return {
                "warnings": 2,
                "open_tickets": 3,
                "profiles": 4,
                "economy_accounts": 5,
                "commands_24h": 6,
            }

    db = FakeDB()
    metrics = asyncio.run(dashboard._guild_metrics(db, 123))

    assert metrics == {
        "warnings": 2,
        "open_tickets": 3,
        "profiles": 4,
        "economy_accounts": 5,
        "commands_24h": 6,
    }
    assert len(db.calls) == 1
    query, params = db.calls[0]
    assert query.count("SELECT COUNT(*)") == 5
    assert params[:5] == (123, 123, 123, 123, 123)
    assert params[5] == 10_000 - 86400
