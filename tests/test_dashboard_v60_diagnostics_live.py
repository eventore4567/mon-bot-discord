import asyncio
import inspect

from web import dashboard_v60_diagnostics


class FakeRow(dict):
    pass


class FakeDB:
    def __init__(self):
        self.query = None
        self.params = None

    async def fetchone(self, query, params):
        self.query = query
        self.params = params
        return FakeRow(
            warnings=4,
            open_tickets=3,
            commands_24h=27,
            sanctions_revision=91,
        )


class FakeBot:
    def __init__(self):
        self.db = FakeDB()
        self.latency = 0.042

    def is_ready(self):
        return True


class FakeGuild:
    id = 123
    member_count = 456


class FakeDashboard:
    @staticmethod
    def now():
        return 1_000_000


def test_diagnostics_batches_independent_reads_and_exposes_timing_and_sse():
    source = inspect.getsource(dashboard_v60_diagnostics)
    assert "await asyncio.gather(" in source
    assert 'response.headers["Server-Timing"]' in source
    assert 'app.router.add_get("/api/guilds/{guild_id}/live/stream"' in source
    assert "await dashboard._administrator_member(guild, user_id)" in source
    assert "await asyncio.sleep(8)" in source


def test_live_metrics_returns_real_operational_counts():
    bot = FakeBot()
    payload = asyncio.run(
        dashboard_v60_diagnostics._live_metrics(FakeDashboard, bot, FakeGuild())
    )
    assert payload["online"] is True
    assert payload["latency_ms"] == 42
    assert payload["members"] == 456
    assert payload["warnings"] == 4
    assert payload["open_tickets"] == 3
    assert payload["commands_24h"] == 27
    assert payload["sanctions_revision"] == 91
    assert "FROM sanctions" in bot.db.query
    assert bot.db.params[0] == 123
