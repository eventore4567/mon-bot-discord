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


def test_les_routes_modules_sont_enregistrees_et_l_etat_vient_de_setup_v2_core():
    """Dashboard et /setup lisent et écrivent la même vérité (module_settings)."""
    source = inspect.getsource(dashboard_v60_diagnostics)
    assert 'app.router.add_get("/api/guilds/{guild_id}/modules", handle_modules_get)' in source
    assert 'app.router.add_post("/api/guilds/{guild_id}/modules", handle_modules_post)' in source
    assert "core.module_state(" in source
    assert "core.set_module_enabled(" in source and "core.reset_module(" in source
    # La vue d'ensemble croise les ressources avec l'interrupteur : désactivé → INACTIF,
    # non configuré → NON CONFIGURÉ, même si un salon traîne en base.
    assert "MODULE_STATE_DISABLED" in source and "MODULE_STATE_NOT_CONFIGURED" in source
    assert '"goodbye"' in source and '"economy"' in source


def test_l_interface_propose_activer_desactiver_par_module():
    from web import dashboard_unified_v2

    html = dashboard_unified_v2.INDEX_HTML
    assert "async function toggleModule(module,action)" in html
    assert "/modules`,{method:'POST'" in html
    assert 'data-action="enable"' in html and 'data-action="disable"' in html
    assert "goodbye:'Départs'" in html and "economy:'Économie'" in html
