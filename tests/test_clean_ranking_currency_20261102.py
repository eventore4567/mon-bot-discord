"""Regression checks for compact ranking and consistent currency customization."""
import inspect
from unittest.mock import AsyncMock, SimpleNamespace
import pytest

from cogs import economy, levels, setup_v2_core, setup_v2_ui
from sentrix_setup_v116 import MODULE_BY_KEY, _open_currency_config


def test_economy_leaderboard_is_simple_not_monospaced():
    source = inspect.getsource(economy.Economy.economyleaderboard.callback)
    assert 'texte="\\n".join(top)' in source
    assert 'aligne=True' not in source
    assert 'sx_panels.Section("Top 10"' in source
    assert "Ton classement" in source
    assert 'discord.utils.escape_markdown' in source


def test_levels_leaderboard_always_shows_xp_and_level():
    source = inspect.getsource(levels.Levels.leaderboard_levels.callback)
    assert 'texte="\\n".join(top)' in source
    assert 'aligne=True' not in source
    assert 'Niv. {niveau}' in source
    assert 'Niveau {level}' in source
    assert 'nombre(xp)' in source


def test_active_setup_currency_route_and_emoji_upload_are_available():
    module = MODULE_BY_KEY["economy"]
    assert any(s.key == "currency" and s.action == "currency-config" for s in module.sections)
    assert "EconomyManageView" in inspect.getsource(_open_currency_config)
    view = setup_v2_ui.EconomyManageView(
        SimpleNamespace(bot=object(), guild=SimpleNamespace(id=1234)), 5678,
    )
    labels = {getattr(item, "label", "") for item in view.children}
    assert "Nom et emoji de la monnaie" in labels
    assert "Importer un emoji" in labels
    modal = setup_v2_ui.CurrencyEmojiUploadModal(view)
    assert any(isinstance(item, setup_v2_ui.discord.ui.Label) for item in modal.children)


@pytest.mark.asyncio
async def test_currency_name_and_symbol_shared_with_profile(monkeypatch):
    awaitable = AsyncMock()
    db = SimpleNamespace(execute=AsyncMock(), set_stats_settings=AsyncMock())
    bot = SimpleNamespace(db=db)
    monkeypatch.setattr(setup_v2_core, "ensure_schema", awaitable)
    await setup_v2_core.set_currency(
        bot, 1234, "Jeton", "Jetons", "<:jeton:123456789012345678>",
        actor_id=5678,
    )
    sql, params = db.execute.await_args.args
    assert params[1:4] == ("Jeton", "Jetons", "<:jeton:123456789012345678>")
    db.set_stats_settings.assert_awaited_once_with(
        1234, {"economy_emoji": "<:jeton:123456789012345678>"}
    )


def test_stats_economy_input_supports_full_custom_emoji():
    source = inspect.getsource(levels.StatsEconomyModal)
    assert "max_length=64" in source
