"""Non-consensual duels must never start; retries/timeouts clean locks."""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
import pytest
from cogs import games_economy, minigames
from utils import game_duel_invites, game_rewards, slash_catalog


def _interaction(user_id: int):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_only_target_may_accept_and_challenger_may_cancel(monkeypatch):
    edits = AsyncMock()
    monkeypatch.setattr(game_duel_invites.panels, "editer", edits)
    started, cancelled = AsyncMock(), AsyncMock()
    invite = game_duel_invites.DuelInvitation(
        challenger_id=101, opponent_id=202, start=started, cancel=cancelled,
    )
    invite.message = SimpleNamespace(id=9)
    stranger = _interaction(303)
    await invite.resolve(stranger, "accept")
    await invite.resolve(_interaction(101), "accept")
    assert invite.status == "pending"
    started.assert_not_awaited()
    cancelled.assert_not_awaited()

    target = _interaction(202)
    await invite.resolve(target, "accept")
    assert invite.status == "accepted"
    started.assert_awaited_once_with(invite.message)
    cancelled.assert_not_awaited()
    target.response.defer.assert_awaited_once()
    await invite.resolve(target, "accept")
    started.assert_awaited_once()
    edits.assert_not_awaited()


@pytest.mark.asyncio
async def test_refusal_and_timeout_release_locks_without_starting_or_rewarding(monkeypatch):
    edits = AsyncMock()
    monkeypatch.setattr(game_duel_invites.panels, "editer", edits)
    for action in ("decline", "timeout"):
        start, cancel = AsyncMock(), AsyncMock()
        invite = game_duel_invites.DuelInvitation(
            challenger_id=101, opponent_id=202, start=start, cancel=cancel,
        )
        invite.message = SimpleNamespace(id=10)
        if action == "decline":
            await invite.resolve(_interaction(202), "decline")
            assert invite.status == "declined"
        else:
            await invite.on_timeout()
            assert invite.status == "expired"
        cancel.assert_awaited_once()
        start.assert_not_awaited()
    assert edits.await_count == 2


def test_all_multiplayer_games_require_acceptance():
    import inspect
    source = inspect.getsource(games_economy.GamesDuels)
    assert source.count("await self._invite(") == 6
    assert 'await self._invite(ctx, "duel"' in source
    for name in ("numberduel", "quizduel", "reactionduel", "connect4", "fight"):
        assert f'await self._invite(ctx, "{name}"' in source
    morpion = inspect.getsource(minigames.Minigames.tictactoe.callback)
    assert "DuelInvitation(" in morpion
    assert "acquire_play_lock" in morpion
    # A pending invitation should not trigger cooldowns or rewards.
    helper = inspect.getsource(games_economy.GamesDuels._invite)
    assert "release_play_lock" in helper
    assert "touch_cooldown" not in helper


def test_new_games_are_real_commands_and_in_both_catalogs():
    games = {"doors", "emojiorder", "bossfight"}
    names = {cmd.name for cmd in games_economy.GamesRapides.__cog_commands__}
    assert games <= names
    assert games <= set(games_economy.GAME_CATALOG)
    slash = {x.source: x.path for x in slash_catalog.CATALOG}
    assert slash["doors"] == "games quick doors"
    assert slash["emojiorder"] == "games quick emojiorder"
    assert slash["bossfight"] == "games quick bossfight"


@pytest.mark.asyncio
async def test_mystery_doors_is_owner_only_and_one_click(monkeypatch):
    view = games_economy._DoorsView(12)
    button = view.children[0]
    monkeypatch.setattr(games_economy.panels, "vue_source", lambda _item: view)
    monkeypatch.setattr(games_economy.panels, "terminer_vue", lambda _item: view.stop())
    stranger = _interaction(99)
    assert await view.interaction_check(stranger) is False
    assert view.choice is None
    owner = _interaction(12)
    assert await view.interaction_check(owner) is True
    await button.callback(owner)
    assert view.choice == 1
    owner.response.defer.assert_awaited_once()
    assert all(child.disabled for child in view.children)


@pytest.mark.asyncio
async def test_emoji_memory_disables_buttons_after_wrong_sequence(monkeypatch):
    view = games_economy._EmojiOrderView(5, ["⭐", "🔥", "💎"])
    monkeypatch.setattr(games_economy.panels, "vue_source", lambda _item: view)
    monkeypatch.setattr(games_economy.panels, "terminer_vue", lambda _item: view.stop())
    wrong = next(button for button in view.children if button.token == "🔥")
    await wrong.callback(_interaction(5))
    assert view.picks == ["🔥"]
    assert all(x.disabled for x in view.children)


def test_trivia_emoji_and_color_use_same_message_and_buttons():
    import inspect
    trivia = inspect.getsource(minigames.Minigames.trivia.callback)
    emoji = inspect.getsource(games_economy.GamesRapides.emojiquiz.callback)
    color = inspect.getsource(games_economy.GamesRapides.colorquiz.callback)
    for body in (trivia, emoji, color):
        assert "await panels.editer(" in body
        assert "await view.wait()" in body
    assert "_QuizChoiceView" in trivia
    assert "_EmojiAnswerView" in emoji
