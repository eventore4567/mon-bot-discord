from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
ROOT = Path(__file__).resolve().parents[1]


def test_departures_are_a_real_setup_category():
    from cogs import setup_components_v73 as v73
    from cogs import setup_experience_v74 as v74

    assert "goodbye" in v73.CATEGORY_ORDER
    assert "goodbye" in v74.CATEGORY_ORDER
    assert v73.CATEGORY_META["goodbye"][1] == "Départs"

    setup_source = (ROOT / "cogs" / "setup_control_center.py").read_text()
    assert 'elif self.category == "goodbye"' in setup_source
    assert 'if cle == "goodbye"' in setup_source


def test_command_channels_are_separate_from_automod_and_plain_text():
    from cogs.command_channel_gate import BLOCKED_MESSAGE

    assert BLOCKED_MESSAGE == "Les commandes sont désactivées dans ce salon."

    schema = (ROOT / "database" / "db.py").read_text()
    gate = (ROOT / "cogs" / "command_channel_gate.py").read_text()

    assert "CREATE TABLE IF NOT EXISTS command_blocked_channels" in schema
    assert "SELECT 1 FROM command_blocked_channels" in gate
    assert "panels.texte_court" in gate
    assert "class CommandChannelBlocked" in gate
    assert "_sentrix_channel_blocked" not in gate
    assert "ignored_channels" not in gate


def test_dashboard_can_choose_blocked_command_channels():
    backend = (ROOT / "web" / "setup_dashboard.py").read_text()
    frontend = (ROOT / "web" / "dashboard_ui" / "js" / "40_tools.js").read_text()

    assert '"command_blocked_channels"' in backend
    assert 'action == "command_channels"' in backend
    assert "commandBlockedChannels" in frontend
    assert "action: 'command_channels'" in frontend


def test_commands_access_page_is_visible_in_main_navigation():
    nav = (ROOT / "web" / "dashboard_ui" / "js" / "10_nav.js").read_text()
    boot = (ROOT / "web" / "dashboard_ui" / "js" / "90_boot.js").read_text()

    assert "['Administration', [['access', 'Commandes & accès']]]" in nav
    assert "access: renderAccess" in boot


def test_roles_offer_simple_no_emoji_and_reaction_modes():
    backend = (ROOT / "web" / "setup_dashboard.py").read_text()
    frontend = (ROOT / "web" / "dashboard_ui" / "js" / "35_community.js").read_text()
    runtime = (ROOT / "cogs" / "verification.py").read_text()

    assert "Créer sans emoji" in frontend
    assert "Créer avec emoji" in frontend
    assert "Texte affiché (optionnel)" in frontend
    assert "role_ids: roleIds" in frontend
    assert "label: $('rrLabel').value.trim()" in frontend

    assert 'payload.get("role_ids")' in backend
    assert "self_role_items" in backend
    assert "self_role_items" in runtime
