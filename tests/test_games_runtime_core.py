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


def test_game_answer_matching_is_accent_and_space_tolerant():
    assert game_rewards.answer_matches("  CAFÉ  ", ("cafe",))
    assert game_rewards.answer_matches("Le   Nil", ("nil", "le nil"))
    assert game_rewards.answer_matches("chateau de glace", ("château de glace",))
    assert not game_rewards.answer_matches("dragon", ("pirate",))


def test_skill_reward_stays_bounded_and_adds_progression():
    assert game_rewards.skill_reward(20, difficulty="easy") == 17
    assert game_rewards.skill_reward(20, difficulty="normal") == 20
    assert game_rewards.skill_reward(20, difficulty="hard") == 26
    assert game_rewards.skill_reward(1, difficulty="easy") == 1


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


def test_text_games_use_tolerant_answer_matching_and_primary_display():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "cogs" / "games_economy.py"
    ).read_text(encoding="utf-8")

    assert "def _primary_answer" in source
    assert "game_rewards.answer_matches(msg.content, answer)" in source
    assert "game_rewards.answer_matches(a1, self.answer)" in source
    assert "guild_id and self.bot" not in source

@pytest.mark.asyncio
async def test_finish_community_releases_lock_and_starts_launcher_cooldown(monkeypatch):
    bot = SimpleNamespace()
    cog = games_economy.GamesCommunity(bot)
    released = []
    touched = AsyncMock()
    monkeypatch.setattr(
        game_rewards,
        "release_play_lock",
        lambda *args: released.append(args),
    )
    monkeypatch.setattr(game_rewards, "touch_cooldown", touched)

    await cog._finish_community(10, 20, "wordrace")

    assert released == [(10, 20, "wordrace")]
    touched.assert_awaited_once_with(bot, 10, 20, "wordrace")


def test_community_games_keep_lock_until_finally_cleanup():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "cogs" / "games_economy.py"
    ).read_text(encoding="utf-8")
    community = source.split("class GamesCommunity", 1)[1].split(
        "class _CommunityRaceButtonView", 1
    )[0]

    assert "async def _finish_community" in community
    for game in ("reactionevent", "emoji-race", "lastmessage"):
        block = community.split(f'async def {game.replace("-", "_")}', 1)[1]
        if game != "lastmessage":
            next_marker = "@commands.hybrid_command"
            block = block.split(next_marker, 1)[0]
        assert "finally:" in block
        assert "_finish_community" in block

    text_race = community.split("async def _run_text_race", 1)[1].split(
        '@commands.hybrid_command(name="triviastart"', 1
    )[0]
    assert "finally:" in text_race
    assert "_finish_community" in text_race

    # The old bug released the lock immediately after _start_community(),
    # allowing one launcher to start many concurrent events before cooldown.
    assert 'release_play_lock(guild_id, ctx.author.id, "reactionevent")' not in community
    assert 'release_play_lock(guild_id, ctx.author.id, "emoji-race")' not in community

def test_play_lock_registry_recovers_stale_lock(monkeypatch):
    registry = game_rewards.PlayLockRegistry(ttl=10)
    key = (1, 2, "slots")
    registry._locked[key] = 100.0
    monkeypatch.setattr(game_rewards.time, "monotonic", lambda: 111.0)

    assert registry.try_acquire(1, 2, "slots") is True
    assert key in registry._locked
    assert registry._locked[key] == 111.0


def test_integrity_layer_no_longer_replaces_game_lock_registry():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "cogs" / "integrity_hardening.py"
    ).read_text(encoding="utf-8")

    assert "class _ExpiringPlayLockRegistry" not in source
    assert "game_rewards._registry =" not in source
    block = source.split("def _install_games", 1)[1].split(
        "def _install_runtime_registry_audit", 1
    )[0]
    assert "game_rewards.PlayLockRegistry" in block
    assert "ttl" in block


@pytest.mark.asyncio
async def test_long_game_cooldowns_are_capped_to_short_antispam():
    db = SimpleNamespace(
        get_game_cooldown_remaining=AsyncMock(return_value=0),
    )
    bot = SimpleNamespace(db=db)

    allowed, remaining = await game_rewards.check_cooldown(
        bot, 1, 2, "mining", 600
    )

    assert allowed is True
    assert remaining == 0
    db.get_game_cooldown_remaining.assert_awaited_once_with(
        1, 2, "mining", game_rewards.MAX_PLAY_COOLDOWN_SECONDS
    )


def test_fasttype_challenge_always_mixes_word_number_and_emoji():
    challenge = games_economy._make_fasttype_challenge("normal")
    tokens = challenge.split()

    assert len(tokens) == 4
    assert any(token.isdigit() for token in tokens)
    assert any(token in games_economy.FASTTYPE_WORDS for token in tokens)
    assert any(token in games_economy.FASTTYPE_EMOJIS for token in tokens)


def test_memory_difficulty_changes_sequence_length():
    assert len(games_economy._make_memory_sequence("facile")) == 3
    assert len(games_economy._make_memory_sequence("normal")) == 4
    assert len(games_economy._make_memory_sequence("difficile")) == 6


def test_reaction_round_has_four_unique_decoys_and_one_target():
    options, target = games_economy._reaction_round()

    assert len(options) == 4
    assert len(set(options)) == 4
    assert options.count(target) == 1
    assert all(len(option.split()) == 2 for option in options)


def test_every_solo_game_has_three_risk_reward_choices():
    solo_games = {"adventure", "dungeon", "mining", "fishing", "treasure", "hunt", "explore"}
    assert solo_games <= set(games_economy.SOLO_CHOICES)

    for game in solo_games:
        choices = games_economy.SOLO_CHOICES[game]
        assert len(choices) == 3
        chances = [choice[2] for choice in choices]
        multipliers = [choice[3] for choice in choices]
        assert chances[0] > chances[1] > chances[2]
        assert multipliers[0] < multipliers[1] < multipliers[2]


def test_reactionevent_uses_targeted_safe_button_view():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "cogs" / "games_economy.py"
    ).read_text(encoding="utf-8")
    block = source.split("async def reactionevent", 1)[1].split(
        '@commands.hybrid_command(name="emoji-race"', 1
    )[0]

    assert "options, target = _reaction_round()" in block
    assert "_CommunityRaceButtonView(options, target)" in block
    assert "panels.vue_source(self)" in source
    assert "panels.vue_panneau(self)" in source


def test_minesweeper_is_public_and_has_a_real_command():
    assert "minesweeper" in games_economy.GAME_CATALOG
    assert any(
        command.name == "minesweeper"
        for command in games_economy.GamesRapides.__cog_commands__
    )


def test_typing_and_memory_previews_are_not_plain_copyable_text():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "cogs" / "games_economy.py"
    ).read_text(encoding="utf-8")

    assert "class _PreviewTokensView" in source
    assert "disabled=True" in source

    memory_block = source.split("async def memory", 1)[1].split(
        '@commands.hybrid_command(name="reaction"', 1
    )[0]
    fast_block = source.split("async def fasttype", 1)[1].split(
        "async def _run_word_guess", 1
    )[0]
    assert "_PreviewTokensView(sequence)" in memory_block
    assert "_PreviewTokensView(challenge_tokens)" in fast_block
    assert "Mémorisez les boutons" in memory_block
    assert "non sélectionnables" in fast_block
    assert "Les cases restent visibles" in fast_block
    assert "20 secondes" in fast_block


def test_all_game_buttons_use_original_business_view_after_v2_relocation():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "cogs" / "games_economy.py"
    ).read_text(encoding="utf-8")

    # Le bug production du 23/09 : self.view était devenu Panneau et n'avait plus
    # _lock / winner / selected. Aucun callback jeu ne doit relire self.view.
    assert "view: _HighLowView = self.view" not in source
    assert "view: _SoloChoiceView = self.view" not in source
    assert "view: _CommunityRaceButtonView = self.view" not in source
    assert "view: _MinesweeperView = self.view" not in source
    assert "panels.vue_source(self)" in source
    assert "panels.terminer_vue(self)" in source


def test_speed_race_default_is_short_clear_and_not_memory_only():
    assert games_economy._difficulty_profile("normal")[0] == 4
    assert games_economy._difficulty_profile("difficile")[0] == 6

    from pathlib import Path
    source = (
        Path(__file__).resolve().parents[1] / "cogs" / "games_economy.py"
    ).read_text(encoding="utf-8")
    block = source.split("async def fasttype", 1)[1].split(
        "async def _run_word_guess", 1
    )[0]
    assert "Recopiez-le **dans le chat**" in block
    assert "Les cases restent visibles" in block
    assert "pas besoin de mémoriser" in block
    assert "normalize_answer(answer.content)" in block


def test_adventure_success_is_the_quest_that_grants_temporary_boost():
    from pathlib import Path
    source = (
        Path(__file__).resolve().parents[1] / "cogs" / "games_economy.py"
    ).read_text(encoding="utf-8")
    solo = source.split("async def _run_solo", 1)[1].split(
        '@commands.hybrid_command(name="adventure"', 1
    )[0]
    assert 'if game_name == "adventure":' in solo
    assert "grant_quest_boost" in solo
    assert "Boost de quête" in solo


@pytest.mark.asyncio
async def test_relocated_highlow_button_updates_source_view_without_attribute_error():
    """Reproduit exactement le bug vu sur Discord : le bouton vit dans Panneau,
    mais son état métier (_lock/choice) reste sur _HighLowView."""
    import discord
    from utils import sentrix_panels as panels

    source = games_economy._HighLowView(author_id=123)
    button = source.children[0]
    panel = panels.avec_composants(panels.Panneau(titre="Plus ou moins"), source)

    response = SimpleNamespace(
        edit_message=AsyncMock(),
        send_message=AsyncMock(),
        is_done=lambda: False,
    )
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=123),
        response=response,
    )

    await button.callback(interaction)

    assert source.choice == "plus_haut"
    response.edit_message.assert_awaited_once()
    assert response.edit_message.await_args.kwargs["view"] is panel


@pytest.mark.asyncio
async def test_relocated_solo_choice_button_updates_source_view_without_attribute_error():
    from utils import sentrix_panels as panels

    choices = [("🧭", "Sûr", 0.9, 0.8, "test")]
    source = games_economy._SoloChoiceView(author_id=123, choices=choices)
    button = source.children[0]
    panel = panels.avec_composants(panels.Panneau(titre="Quête"), source)

    response = SimpleNamespace(
        edit_message=AsyncMock(),
        send_message=AsyncMock(),
        is_done=lambda: False,
    )
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=123),
        response=response,
    )

    await button.callback(interaction)

    assert source.selected == choices[0]
    assert response.edit_message.await_args.kwargs["view"] is panel
