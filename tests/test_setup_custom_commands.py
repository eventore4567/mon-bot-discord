"""Décision du 30/10/2026 : plus de slash /custom, configuration dans /setup."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cogs.setup_custom_commands import VALID_NAME, parse_action

ROOT = Path(__file__).resolve().parents[1]


def test_custom_commands_are_no_longer_published_as_slash():
    from utils.slash_catalog import CATALOG
    assert not any(entry.path == "custom" or entry.path.startswith("custom ") for entry in CATALOG)
    assert any(entry.path == "setup" for entry in CATALOG)


def test_custom_setup_page_registered():
    text = (ROOT / "cogs/setup_experience_v74.py").read_text(encoding="utf-8")
    assert 'value="custom_commands"' in text
    assert 'if page == "custom_commands":' in text
    assert "setup_custom_commands.build_page(self)" in text


def test_custom_name_validation():
    assert VALID_NAME.fullmatch("bienvenue")
    assert VALID_NAME.fullmatch("cadeau_vip")
    assert not VALID_NAME.fullmatch("@everyone")
    assert not VALID_NAME.fullmatch("a")
    assert not VALID_NAME.fullmatch("esp ace")


def test_role_actions_reject_unmanageable_role():
    guild = Mock()
    role = Mock()
    role.is_default.return_value = False
    role.managed = False
    role.id = 42
    role.__ge__ = Mock(return_value=True)
    guild.get_role.return_value = role
    guild.me.top_role = Mock()
    with pytest.raises(ValueError, match="sous celui de SentriX"):
        parse_action("role_add", "42", "", guild, {})


def test_money_and_xp_cannot_run_with_disabled_modules():
    guild = SimpleNamespace()
    with pytest.raises(ValueError, match="désactivé"):
        parse_action("money", "500", "", guild, {"economy": "disabled"})
    with pytest.raises(ValueError, match="désactivé"):
        parse_action("xp", "10", "", guild, {"levels": "disabled"})
    assert parse_action("money", "500", "", guild, {"economy": "enabled"}) == (500, 0)
    assert parse_action("xp", "10", "", guild, {"levels": "enabled"}) == (10, 0)


def test_value_caps():
    guild = SimpleNamespace()
    with pytest.raises(ValueError):
        parse_action("money", "1000001", "", guild, {"economy": "enabled"})
    with pytest.raises(ValueError):
        parse_action("xp", "100001", "", guild, {"levels": "enabled"})
