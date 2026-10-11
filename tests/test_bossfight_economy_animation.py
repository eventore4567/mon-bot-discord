"""Régressions bossfight et Économie : animations par phases, / et + identiques."""
import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from cogs import games_economy, minigames
from utils import game_context, game_rewards, game_visuals, slash_catalog, system_features


@pytest.mark.asyncio
async def test_boss_button_shows_attack_then_distinct_counter_then_buttons(monkeypatch):
    ctx = SimpleNamespace(author=SimpleNamespace(id=13), guild=SimpleNamespace(id=33))
    view = games_economy._BossFightView(SimpleNamespace(bot=SimpleNamespace()), ctx, "round-1")
    scenes = []

    async def capture(status, *, scene, buttons):
        scenes.append((scene, status, buttons))

    monkeypatch.setattr(view, "_phase", capture)
    monkeypatch.setattr(games_economy.panels, "vue_source", lambda _button: view)
    monkeypatch.setattr(game_rewards, "secure_randint", lambda lo, hi: lo)
    monkeypatch.setattr(games_economy.asyncio, "sleep", AsyncMock())
    interaction = SimpleNamespace(user=SimpleNamespace(id=13), response=SimpleNamespace(defer=AsyncMock()))
    button = next(child for child in view.children if child.action == "attack")

    await button.callback(interaction)
    assert view.turn == 1
    assert [item[0] for item in scenes] == ["boss-attack", "boss-counter", "boss-attack"]
    assert scenes[0][2] is False
    assert scenes[1][2] is False
    assert scenes[2][2] is True
    assert "Vous attaquez" in scenes[0][1]
    assert "boss" in scenes[1][1].lower()
    assert view.hp < 14 and view.boss_hp < 18


@pytest.mark.asyncio
async def test_shield_and_magic_have_different_gifs_and_shield_blocks(monkeypatch):
    monkeypatch.setattr(games_economy.panels, "vue_source", lambda btn: btn.view)
    monkeypatch.setattr(games_economy.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(game_rewards, "secure_randint", lambda lo, hi: lo)
    monkeypatch.setattr(game_rewards, "secure_chance", lambda probability: True)
    for action, scene in (("guard", "boss-guard"), ("power", "boss-power")):
        ctx = SimpleNamespace(author=SimpleNamespace(id=7), guild=SimpleNamespace(id=9))
        view = games_economy._BossFightView(SimpleNamespace(bot=SimpleNamespace()), ctx, "round-2")
        scenes = []

        async def capture(status, *, scene, buttons):
            scenes.append(scene)

        monkeypatch.setattr(view, "_phase", capture)
        interaction = SimpleNamespace(user=SimpleNamespace(id=7), response=SimpleNamespace(defer=AsyncMock()))
        button = next(child for child in view.children if child.action == action)
        await button.callback(interaction)
        assert scenes == [scene, "boss-counter", scene]
        if action == "guard":
            assert view.hp == 14
            assert view.boss_hp == 17
        else:
            assert view.hp == 12
            assert view.boss_hp == 13


def test_boss_scenes_are_distinct_gifs_and_dont_return_broken_url():
    choices = ("boss-attack", "boss-power", "boss-guard", "boss-counter")
    sources = [game_visuals.GIFS[key] for key in choices]
    assert len(set(sources)) == len(sources)
    assert all(value.startswith("https://media.giphy.com/media/") for value in sources)
    assert all(value.endswith("/giphy.gif") for value in sources)
    assert game_visuals.GIFS["win"] != game_visuals.GIFS["loss"]


@pytest.mark.asyncio
async def test_games_defeat_never_says_action_impossible(monkeypatch):
    from utils import design_system
    bot = SimpleNamespace(db=SimpleNamespace(get_design_settings=AsyncMock(
        return_value=design_system.DEFAULT_DESIGN_SETTINGS,
    )))
    async def decorate(embed, **kwargs):
        return embed
    monkeypatch.setattr(game_visuals, "decorate_embed_checked", decorate)
    embed = await games_economy._embed(
        bot, 123, title="Combat de boss — Défaite",
        description="Vous êtes vaincu.", kind="danger", scene="loss",
    )
    assert "Action impossible" not in embed.title
    assert "Combat de boss" in embed.title
    assert game_context.pictogramme_de_titre("Combat de boss") == "🐲"
    assert game_context.pictogramme_de_titre("Portes mystères") == "🚪"


@pytest.mark.asyncio
async def test_economy_toggle_controls_game_payouts_without_altering_playability(monkeypatch):
    async def test_case(enabled):
        async def record(gid, uid, name, sid, result, amount, metadata):
            return True, "GAME-123456", amount

        db = SimpleNamespace(
            fetchone=AsyncMock(return_value={"enabled": int(enabled)}),
            get_game_settings=AsyncMock(return_value={"daily_limit": 10}),
            record_game_reward=AsyncMock(side_effect=record),
            count_game_rewards_today=AsyncMock(return_value=0),
        )
        bot = SimpleNamespace(db=db, get_guild=lambda _id: None)
        feature = AsyncMock(return_value=enabled)
        monkeypatch.setattr(system_features, "is_system_enabled", feature)
        async def boost(_db, _gid, _uid, amount):
            return amount, None
        from utils import temporary_boosts
        monkeypatch.setattr(temporary_boosts, "apply_money_boost", boost)
        result = await game_rewards.reward_game_winner(
            bot, 18, 42, "bossfight", 70, f"session-{enabled}", "win",
        )
        assert result.success
        assert result.amount == (70 if enabled else 0)
        assert result.reason == ("ok" if enabled else "economy_disabled")
        assert db.record_game_reward.await_args.args[5] == (70 if enabled else 0)
        feature.assert_awaited_once()
        return result

    off = await test_case(False)
    on = await test_case(True)
    assert off.amount == 0 and on.amount == 70


def test_prefix_and_slash_game_paths_reuse_the_same_command_callbacks():
    commands = {}
    for cls in (
        games_economy.GamesRapides,
        games_economy.GamesDuels,
        minigames.Minigames,
    ):
        commands.update({command.name: command for command in cls.__cog_commands__})
    paths = {item.source: item.path for item in slash_catalog.CATALOG}
    for game in ("bossfight", "doors", "emojiorder", "duel", "trivia", "tictactoe"):
        assert game in commands
        assert paths[game].startswith("games ")
        assert callable(commands[game].callback)
        assert inspect.iscoroutinefunction(commands[game].callback)
