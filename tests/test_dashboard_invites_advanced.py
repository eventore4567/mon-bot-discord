from __future__ import annotations

import inspect
from pathlib import Path

from web import dashboard_api_invites


ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "web" / "dashboard_ui" / "js" / "40_tools.js").read_text(encoding="utf-8")
DASHBOARD = (ROOT / "web" / "dashboard.py").read_text(encoding="utf-8")
INVITES_COG = (ROOT / "cogs" / "invites.py").read_text(encoding="utf-8")


def test_invite_dashboard_api_registers_advanced_routes():
    source = inspect.getsource(dashboard_api_invites.register)
    for route in (
        '"/api/guilds/{guild_id}/invites/analytics"',
        '"/api/guilds/{guild_id}/invites/inviters/{user_id}"',
        '"/api/guilds/{guild_id}/invites/codes/{code}"',
        '"/api/guilds/{guild_id}/invites/leaderboard-hidden"',
        '"/api/guilds/{guild_id}/invites/sync"',
    ):
        assert route in source


def test_invite_dashboard_never_invents_historical_attribution_on_sync():
    source = inspect.getsource(dashboard_api_invites.register)
    sync_start = source.index("async def sync_post")
    sync_section = source[sync_start:]
    assert "cache_guild_invites" in sync_section
    assert "record_invite_join" not in sync_section
    assert "Aucune attribution historique" in sync_section


def test_invite_dashboard_has_periods_retention_sources_codes_and_csv():
    for marker in (
        "Analytics invitations",
        "24h",
        "7d",
        "30d",
        "Rétention",
        "Sources d’arrivée",
        "Classement des invitants",
        "Codes d’invitation actifs",
        "Synchroniser",
        "Exporter CSV",
        "data-invited-list",
        "data-invite-label",
        "data-hide-inviter",
    ):
        assert marker in UI


def test_invite_dashboard_routes_are_registered_in_main_app():
    assert "dashboard_api_invites" in DASHBOARD
    assert "register_invite_routes" in DASHBOARD


def test_invite_dashboard_has_no_periodic_dom_churn():
    start = UI.index("let inviteWindow")
    end = UI.index("/* Sauvegardes & historique */", start)
    section = UI[start:end]
    assert "setInterval(" not in section
    assert "MutationObserver" not in section


def test_invite_commands_expose_list_codes_and_safe_sync():
    for marker in (
        'name="invited-list"',
        'name="invite-codes"',
        'name="sync-invites"',
        "Aucune attribution historique de membre n'a été inventée.",
    ):
        assert marker in INVITES_COG
    sync_start = INVITES_COG.index("async def sync_invites")
    sync_section = INVITES_COG[sync_start:sync_start + 4000]
    assert "record_invite_join" not in sync_section
    assert "cache_guild_invites" in sync_section


def test_invite_command_suite_is_expanded_without_destructive_reset():
    for marker in (
        'name="invite-stats"',
        'name="invite-rank"',
        'name="invite-history"',
        'name="invite-info"',
        'name="invite-sources"',
        'name="invite-retention"',
        'name="invite-label"',
        'name="invite-unlabel"',
        'name="invite-search"',
        '"invite-sync"',
        '"resync-invites"',
    ):
        assert marker in INVITES_COG
    assert 'name="reset-invites"' not in INVITES_COG
    assert 'name="purge-invites"' not in INVITES_COG
