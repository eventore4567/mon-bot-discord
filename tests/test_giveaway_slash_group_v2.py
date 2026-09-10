from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cogs" / "giveaway_center.py"


def text() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_giveaway_center_compiles():
    source = text()
    ast.parse(source, filename=str(SOURCE))


def test_giveaway_is_a_real_app_command_group():
    source = text()
    assert "from discord import app_commands" in source
    assert "giveaway_slash = app_commands.Group(" in source
    assert 'name="giveaway"' in source
    for action in ("list", "create", "end", "reroll", "cancel", "blacklist", "unblacklist"):
        assert f'@giveaway_slash.command(name="{action}"' in source


def test_mutating_giveaway_slash_actions_have_admin_guard():
    source = text()
    assert "async def _slash_admin" in source
    assert source.count("@app_commands.default_permissions(administrator=True)") >= 6
    assert source.count("if not await self._slash_admin(interaction):") >= 6


def test_prefix_giveaway_surface_is_preserved():
    source = text()
    assert '@commands.group(name="giveaway"' in source
    assert '@giveaway.command(name="create"' in source
    assert '@giveaway.command(name="end"' in source
    assert '@giveaway.command(name="reroll"' in source
