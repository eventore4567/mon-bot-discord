"""The server may enable XP, but SentriX alone controls its automatic rate."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.levels import Levels, XP_MIN_FALLBACK, XP_MAX_FALLBACK


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_old_server_xp_rate_is_ignored():
    cog = Levels.__new__(Levels)
    cog.bot = SimpleNamespace(db=SimpleNamespace())
    cog._apply_xp_delta = AsyncMock(return_value=(100, 1, False))
    message = SimpleNamespace(
        guild=SimpleNamespace(id=55),
        author=SimpleNamespace(id=77),
    )
    # Old per-guild values must not allow huge rewards or zero cooldown.
    old_settings = {"xp_min": 5000, "xp_max": 5000, "xp_cooldown": 0}
    old_config = {"xp_multiplier": 5}
    with patch("cogs.levels.random.randint", return_value=XP_MIN_FALLBACK) as randint, \\
         patch("cogs.levels.temporary_boosts.apply_xp_boost", new_callable=AsyncMock, return_value=(XP_MIN_FALLBACK, None)):
        await cog._process_xp(message, old_settings, old_config)
    randint.assert_called_once_with(XP_MIN_FALLBACK, XP_MAX_FALLBACK)
    cog._apply_xp_delta.assert_awaited_once_with(55, 77, XP_MIN_FALLBACK)


def test_no_amount_selector_in_stats_config():
    source = (ROOT / "cogs/levels.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert "class StatsXPModal" not in source
    assert 'custom_id="cfg:edit_xp"' not in source
    assert "gained = random.randint(XP_MIN_FALLBACK, XP_MAX_FALLBACK)" in source
    assert "cooldown = XP_COOLDOWN_FALLBACK" in source


def test_dashboard_rejects_custom_auto_rates():
    source = (ROOT / "web/dashboard_api_community.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert 'if any(key in payload for key in ("xp_min", "xp_max", "xp_cooldown", "xp_multiplier")):' in source


def test_dashboard_xp_controls_removed():
    source = (ROOT / "web/dashboard_ui/js/35_community.js").read_text(encoding="utf-8")
    assert 'id="lvMin"' not in source
    assert 'id="lvMax"' not in source
    assert 'id="lvCd"' not in source
    assert "field('Multiplicateur XP'" not in source
