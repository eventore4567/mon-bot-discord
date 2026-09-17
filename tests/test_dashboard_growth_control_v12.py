from types import SimpleNamespace

from web import dashboard_growth_control_v12 as growth
from web import dashboard_growth_control_v12_fix as growth_fix


class DummyDashboard(SimpleNamespace):
    pass


class _Router:
    def __init__(self):
        self.routes = []

    def add_get(self, path, handler):
        self.routes.append(("GET", path))

    def add_post(self, path, handler):
        self.routes.append(("POST", path))


def _dashboard():
    def build_app(bot):
        return SimpleNamespace(router=_Router())

    return DummyDashboard(
        INDEX_HTML='<!doctype html><html><head></head><body><div id="content"></div></body></html>',
        build_app=build_app,
    )


def test_growth_v12_keeps_api_routes_without_client_side_navigation():
    """Depuis V15, les 9 pages Croissance/Opérations sont rendues nativement par le
    frontend V2. V12 ne doit plus injecter de boutons dans la navigation ni rendre ces
    onglets lui-même (double « Statistiques », rendus concurrents dans #content,
    requêtes dupliquées, skeleton permanent — mesuré en navigateur réel), mais ses
    routes API restent la source des données de V15."""
    dashboard = _dashboard()
    assert growth.install(dashboard) is True
    assert growth_fix.install(dashboard) is True
    html = dashboard.INDEX_HTML

    # Contrat de boot (sentrix_dashboard_finalizer_v7 + V13) : marqueurs présents.
    assert 'id="sentrix-growth-v12-css"' in html
    assert 'id="sentrix-growth-v12-js"' in html
    assert "__sentrixGrowthV12Api" in html
    assert "__sentrixGrowthV12SyntaxGuard" in html

    # Plus aucun routeur client concurrent de V15.
    for retired in ("data-sx12-tab", "ensureNav", "renderStats", "MutationObserver", "setInterval", "sx12-nav-new"):
        assert retired not in html, retired

    # Les routes API dont V15 dépend sont toujours installées.
    app = dashboard.build_app(SimpleNamespace(db=None, add_listener=lambda *a, **k: None))
    registered = {path for _method, path in app.router.routes}
    assert "/api/guilds/{guild_id}/growth/stats" in registered
    assert "/api/guilds/{guild_id}/growth/invitations" in registered
    assert "/api/guilds/{guild_id}/growth/webhooks" in registered
    assert "/api/guilds/{guild_id}/automation/reactions" in registered
    assert ("POST", "/api/guilds/{guild_id}/automation/reactions") in app.router.routes


def test_growth_v12_syntax_guard_still_marks_the_bundle():
    dashboard = _dashboard()
    assert growth.install(dashboard) is True
    assert growth_fix.install(dashboard) is True
    html = dashboard.INDEX_HTML
    for bad in growth_fix._REPLACEMENTS:
        assert bad not in html
    assert growth_fix.MARKER in html


def test_auto_reaction_emoji_validation_accepts_unicode_and_discord_custom():
    assert growth._emoji_valid("❤️") is True
    assert growth._emoji_valid("🔥") is True
    assert growth._emoji_valid("<:sentrix:123456789012345678>") is True
    assert growth._emoji_valid("<a:sentrix:123456789012345678>") is True
    assert growth._emoji_valid("") is False
    assert growth._emoji_valid("<broken>") is False


def test_growth_v12_wraps_build_app_only_once():
    dashboard = _dashboard()
    assert growth.install(dashboard) is True
    wrapped = dashboard.build_app
    assert getattr(wrapped, "_sentrix_growth_v12_routes", False) is True
    assert growth.install(dashboard) is True
    assert dashboard.build_app is wrapped


def test_finalizer_mentions_growth_v12_after_unified_adapter():
    source = open("sentrix_dashboard_finalizer_v7.py", encoding="utf-8").read()
    assert "dashboard_growth_control_v12.install(dashboard)" in source
    assert "dashboard_growth_control_v12_fix.install(dashboard)" in source
    assert source.index("dashboard_unified_adapter_v9.install(dashboard)") < source.index("dashboard_growth_control_v12.install(dashboard)")
    assert source.index("dashboard_growth_control_v12.install(dashboard)") < source.index("dashboard_growth_control_v12_fix.install(dashboard)")
    assert 'id="sentrix-growth-v12-js"' in source
