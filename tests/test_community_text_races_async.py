"""Régressions des courses communautaires non bloquantes.

Une manche dure 15 à 25 secondes, mais la commande du lanceur doit rendre
la main dès la publication du défi. Les gains et les verrous restent gérés
par la tâche de fond, y compris en cas de timeout ou d'erreur d'envoi.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from cogs import games_economy


def _context():
    return SimpleNamespace(
        guild=SimpleNamespace(id=123),
        channel=SimpleNamespace(id=456),
        author=SimpleNamespace(id=789),
    )


def _prepare(monkeypatch, *, send=None):
    bot = SimpleNamespace(wait_for=AsyncMock())
    cog = games_economy.GamesCommunity(bot)
    ctx = _context()
    cog._start_community = AsyncMock(return_value=(True, "", "session-1"))
    cog._finish_community = AsyncMock()
    send = send or AsyncMock(return_value=None)
    monkeypatch.setattr(games_economy.panels, "envoyer", send)
    monkeypatch.setattr(games_economy.panels, "depuis_embed", lambda embed: embed)
    monkeypatch.setattr(games_economy, "_embed", AsyncMock(return_value="panneau"))
    monkeypatch.setattr(games_economy, "_reward_line", lambda reward: "")
    return cog, bot, ctx, send


def test_wordrace_returns_before_the_25_second_wait(monkeypatch):
    async def scenario():
        cog, bot, ctx, send = _prepare(monkeypatch)
        answer_ready = asyncio.Event()
        winning_message = SimpleNamespace(
            channel=ctx.channel,
            author=SimpleNamespace(bot=False, id=10, mention="<@10>"),
            content="CHAT",
        )

        async def wait_for(event, *, check, timeout):
            assert event == "message"
            assert timeout == 25
            assert check(winning_message) is True
            await answer_ready.wait()
            return winning_message

        bot.wait_for = AsyncMock(side_effect=wait_for)
        reward = AsyncMock(return_value=object())
        monkeypatch.setattr(games_economy.game_rewards, "reward_game_winner", reward)
        monkeypatch.setattr(games_economy.game_rewards, "skill_reward", lambda amount, **kw: amount)

        await asyncio.wait_for(
            cog._run_text_race(ctx, "wordrace", "Course au mot", "TACH", "CHAT", 25, 20),
            timeout=1,
        )
        assert send.await_count == 1
        assert len(cog._community_tasks) == 1
        await asyncio.sleep(0)
        bot.wait_for.assert_awaited_once()
        assert cog._finish_community.await_count == 0
        answer_ready.set()
        await asyncio.gather(*tuple(cog._community_tasks))
        assert send.await_count == 2
        reward.assert_awaited_once()
        cog._finish_community.assert_awaited_once_with(123, 789, "wordrace")

    asyncio.run(scenario())


def test_timeout_announces_answer_and_releases_lock(monkeypatch):
    async def scenario():
        cog, bot, ctx, send = _prepare(monkeypatch)
        bot.wait_for = AsyncMock(side_effect=asyncio.TimeoutError)

        await cog._run_text_race(ctx, "mathrace", "Course mathématique", "2 + 2", "4", 15, 18)
        await asyncio.gather(*tuple(cog._community_tasks))
        assert send.await_count == 2
        cog._finish_community.assert_awaited_once_with(123, 789, "mathrace")

    asyncio.run(scenario())


def test_publishing_failure_releases_lock_without_cooldown(monkeypatch):
    async def scenario():
        send = AsyncMock(side_effect=RuntimeError("Discord indisponible"))
        cog, bot, ctx, _ = _prepare(monkeypatch, send=send)
        release = Mock()
        monkeypatch.setattr(games_economy.game_rewards, "release_play_lock", release)

        try:
            await cog._run_text_race(ctx, "wordrace", "Course au mot", "TACH", "CHAT", 25, 20)
        except RuntimeError as exc:
            assert "Discord indisponible" in str(exc)
        else:
            raise AssertionError("Le message d'erreur devait remonter")

        release.assert_called_once_with(123, 789, "wordrace")
        cog._finish_community.assert_not_awaited()
        assert not cog._community_tasks

    asyncio.run(scenario())
