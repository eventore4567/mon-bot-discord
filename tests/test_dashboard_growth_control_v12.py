from types import SimpleNamespace

from web import dashboard_growth_control_v12 as growth
from web import dashboard_growth_control_v12_fix as growth_fix


class DummyDashboard(SimpleNamespace):
    pass


def _dashboard():
    def build_app(bot):
        return SimpleNamespace(router=SimpleNamespace())

    return DummyDashboard(
        INDEX_HTML='<!doctype html><html><head></head><body><div id="content"></div></body></html>',
        build_app=build_app,
    )


def test_growth_v12_injects_real_navigation_and_surfaces():
    dashboard = _dashboard()
    assert growth.install(dashboard) is True
    assert growth_fix.install(dashboard) is True
    html = dashboard.INDEX_HTML
    assert 'id="sentrix-growth-v12-css"' in html
    assert 'id="sentrix-growth-v12-js"' in html
    assert "Statistiques" in html
    assert "Invitations" in html
    assert "Réactions automatiques" in html
    assert "Automatisations" in html
    assert "Activité staff" in html
    assert "Historique & audit" in html
    assert "Sauvegardes" in html
    assert "Maintenance" in html
    assert "Webhooks & intégrations" in html
    assert "/automation/reactions" in html
    assert "__sentrixGrowthV12SyntaxGuard" in html


def test_growth_v12_syntax_guard_removes_known_bad_badge_literals():
    dashboard = _dashboard()
    assert growth.install(dashboard) is True
    assert growth_fix.install(dashboard) is True
    html = dashboard.INDEX_HTML
    for bad in growth_fix._REPLACEMENTS:
        assert bad not in html
    assert '`${fmt(d.items.length)} liens`,"blue"' in html
    assert '`${fmt(d.items.length)} règle(s)`,"blue"' in html


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
