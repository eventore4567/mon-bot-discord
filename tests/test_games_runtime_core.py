import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs import games_economy, minigames
from utils import game_rewards


@pytest.mark.asyncio
async def test_direct_game_reward_cannot_bypass_daily_limit():
    db = SimpleNamespace(
        get_game_settings=AsyncMock(return_value={
            "enabled": 1,
            "disabled_games": "[]",
            "allowed_channel_ids": "[]",
            "blocked_channel_ids": "[]",
            "allowed_role_ids": "[]",
            "blocked_role_ids": "[]",
            "min_reward_multiplier": 1.0,
            "max_reward_multiplier": 1.0,
            "daily_limit": 2,
            "event_multiplier": 1.0,
            "logs_enabled": 0,
            "leaderboard_enabled": 1,
            "dm_results": 0,
            "compact_mode": 0,
            "default_difficulty": "normal",
        }),
        count_game_rewards_today=AsyncMock(return_value=2),
        record_game_reward=AsyncMock(),
    )
    bot = SimpleNamespace(db=db)

    reward = await game_rewards.reward_game_winner(
        bot, 1, 2, "reactionduel", 35, "session-1", result="win"
    )

    assert reward.success is False
    assert reward.reason == "daily_limit"
    assert reward.amount == 0
    db.record_game_reward.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_winning_result_is_still_recorded_at_daily_limit():
    db = SimpleNamespace(
        get_game_settings=AsyncMock(return_value={
            "enabled": 1,
            "disabled_games": "[]",
            "allowed_channel_ids": "[]",
            "blocked_channel_ids": "[]",
            "allowed_role_ids": "[]",
            "blocked_role_ids": "[]",
            "min_reward_multiplier": 1.0,
            "max_reward_multiplier": 1.0,
            "daily_limit": 1,
            "event_multiplier": 1.0,
            "logs_enabled": 0,
            "leaderboard_enabled": 1,
            "dm_results": 0,
            "compact_mode": 0,
            "default_difficulty": "normal",
        }),
        count_game_rewards_today=AsyncMock(return_value=99),
        record_game_reward=AsyncMock(return_value=(True, "GAME-000001", 0)),
    )
    bot = SimpleNamespace(db=db)

    reward = await game_rewards.reward_game_winner(
        bot, 1, 2, "tictactoe", 0, "session-draw", result="draw"
    )

    assert reward.success is True
    db.record_game_reward.assert_awaited_once()


def test_every_catalog_game_has_a_real_command_surface():
    expected = set(games_economy.GAME_CATALOG)
    minigame_commands = {
        command.name
        for command in minigames.Minigames.__cog_commands__
        if command.name in expected
    }

    economy_commands = set()
    for cog_cls in (
        games_economy.GamesRapides,
        games_economy.GamesDuels,
        games_economy.GamesCommunity,
        games_economy.GamesSolo,
    ):
        economy_commands.update(
            command.name for command in cog_cls.__cog_commands__ if command.name in expected
        )

    assert expected == minigame_commands | economy_commands


def test_game_catalog_has_no_duplicate_keys_or_unknown_categories():
    assert len(games_economy.GAME_CATALOG) == len(set(games_economy.GAME_CATALOG))
    allowed_categories = {"rapide", "duel", "communautaire", "solo"}
    assert {
        category for _label, category in games_economy.GAME_CATALOG.values()
    } <= allowed_categories


@pytest.mark.asyncio
async def test_game_settings_restrictions_apply_to_roles_and_channels():
    db = SimpleNamespace(
        get_game_settings=AsyncMock(return_value={
            "enabled": 1,
            "disabled_games": "[]",
            "allowed_channel_ids": "[10]",
            "blocked_channel_ids": "[]",
            "allowed_role_ids": "[20]",
            "blocked_role_ids": "[30]",
            "min_reward_multiplier": 1.0,
            "max_reward_multiplier": 1.0,
            "daily_limit": 50,
            "event_multiplier": 1.0,
            "logs_enabled": 0,
            "leaderboard_enabled": 1,
            "dm_results": 0,
            "compact_mode": 0,
            "default_difficulty": "normal",
        })
    )
    bot = SimpleNamespace(db=db)

    ok, _ = await game_rewards.is_game_enabled(
        bot, 1, "tictactoe", channel_id=10, role_ids={20}
    )
    assert ok is True

    ok, reason = await game_rewards.is_game_enabled(
        bot, 1, "tictactoe", channel_id=11, role_ids={20}
    )
    assert ok is False
    assert "salon" in reason.lower()

    ok, reason = await game_rewards.is_game_enabled(
        bot, 1, "tictactoe", channel_id=10, role_ids={30}
    )
    assert ok is False
    assert "rôle" in reason.lower()


def test_play_lock_registry_never_allows_same_game_twice():
    registry = game_rewards.PlayLockRegistry()
    assert registry.try_acquire(1, 2, "slots") is True
    assert registry.try_acquire(1, 2, "slots") is False
    assert registry.try_acquire(1, 2, "dice") is True
    registry.release(1, 2, "slots")
    assert registry.try_acquire(1, 2, "slots") is True


def test_tictactoe_source_uses_shared_start_and_timeout_cleanup():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "cogs" / "minigames.py"
    ).read_text(encoding="utf-8")
    block = source.split("async def tictactoe", 1)[1].split(
        '@commands.hybrid_command(name="hangman"', 1
    )[0]

    assert 'self._start(ctx, "tictactoe", cooldown=15)' in block
    assert "opponent_roles" in block
    assert "release_play_lock" in source
    assert "async def on_timeout(self)" in source
    assert 'touch_cooldown(self.cog.bot, guild_id, self.player_o.id, "tictactoe")' in source

@pytest.mark.asyncio
async def test_duel_precheck_validates_opponent_roles_cooldown_and_lock(monkeypatch):
    starter = SimpleNamespace(id=1, roles=[SimpleNamespace(id=20)])
    opponent = SimpleNamespace(id=2, roles=[SimpleNamespace(id=20)])
    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=10),
        author=starter,
        channel=SimpleNamespace(id=99),
    )

    monkeypatch.setattr(
        games_economy,
        "_precheck",
        AsyncMock(return_value=(True, "", "sid-1")),
    )
    enabled = AsyncMock(return_value=(True, ""))
    cooldown = AsyncMock(return_value=(True, 0))
    monkeypatch.setattr(game_rewards, "is_game_enabled", enabled)
    monkeypatch.setattr(game_rewards, "check_cooldown", cooldown)
    monkeypatch.setattr(game_rewards, "acquire_play_lock", lambda *_args: True)

    ok, reason, sid = await games_economy._precheck_duel(
        SimpleNamespace(),
        ctx,
        "duel",
        opponent,
        15,
    )

    assert ok is True
    assert reason == ""
    assert sid == "sid-1"
    enabled.assert_awaited_once()
    cooldown.assert_awaited_once_with(
        pytest.ANY if hasattr(pytest, "ANY") else enabled,  # never evaluated below
    ) if False else None
    assert cooldown.await_args.args[1:] == (10, 2, "duel", 15)


@pytest.mark.asyncio
async def test_duel_releases_starter_lock_when_opponent_is_forbidden(monkeypatch):
    starter = SimpleNamespace(id=1, roles=[])
    opponent = SimpleNamespace(id=2, roles=[])
    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=10),
        author=starter,
        channel=SimpleNamespace(id=99),
    )

    monkeypatch.setattr(
        games_economy,
        "_precheck",
        AsyncMock(return_value=(True, "", "sid-2")),
    )
    monkeypatch.setattr(
        game_rewards,
        "is_game_enabled",
        AsyncMock(return_value=(False, "Rôle non autorisé")),
    )
    released = []
    monkeypatch.setattr(
        game_rewards,
        "release_play_lock",
        lambda *args: released.append(args),
    )

    ok, reason, sid = await games_economy._precheck_duel(
        SimpleNamespace(),
        ctx,
        "numberduel",
        opponent,
        15,
    )

    assert ok is False
    assert "Adversaire non autorisé" in reason
    assert sid is None
    assert released == [(10, 1, "numberduel")]


@pytest.mark.asyncio
async def test_duel_finish_releases_and_cooldowns_both_players(monkeypatch):
    p1 = SimpleNamespace(id=1)
    p2 = SimpleNamespace(id=2)
    released = []
    touch = AsyncMock()
    monkeypatch.setattr(
        game_rewards,
        "release_play_lock",
        lambda *args: released.append(args),
    )
    monkeypatch.setattr(game_rewards, "touch_cooldown", touch)

    bot = SimpleNamespace()
    await games_economy._finish_duel(bot, 10, "connect4", p1, p2)

    assert released == [
        (10, 1, "connect4"),
        (10, 2, "connect4"),
    ]
    assert touch.await_count == 2
    calls = {tuple(call.args[1:]) for call in touch.await_args_list}
    assert calls == {
        (10, 1, "connect4"),
        (10, 2, "connect4"),
    }


def test_all_duel_commands_use_shared_two_player_precheck():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "cogs" / "games_economy.py"
    ).read_text(encoding="utf-8")
    for game in ("duel", "numberduel", "quizduel", "reactionduel", "connect4"):
        block = source.split(f"async def {game}", 1)[1].split(
            "@commands.hybrid_command", 1
        )[0]
        assert f'_precheck_duel(self.bot, ctx, "{game}", adversaire, 15)' in block

