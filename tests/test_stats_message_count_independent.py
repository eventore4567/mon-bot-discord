"""Régression production : +stats affichait 0 quand l'XP était désactivée.

Le compteur de messages n'est PAS une récompense : chaque message humain compte,
même en période de cooldown XP ou dans un salon exclu des niveaux. Les commandes
restent des messages ; elles ne doivent pas générer d'XP si le réglage le refuse.
"""
from __future__ import annotations

import asyncio
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.levels import Levels


def _make_cog(*, levels_enabled: bool, settings: dict | None = None):
    db = SimpleNamespace(
        execute=AsyncMock(),
        get_stats_settings=AsyncMock(
            return_value=settings or {"xp_cooldown": 60}
        ),
        get_guild_config=AsyncMock(return_value=None),
    )
    bot = SimpleNamespace(
        db=db,
        _xp_skip_ids=set(),
        get_context=AsyncMock(return_value=SimpleNamespace(valid=False)),
    )
    cog = Levels.__new__(Levels)
    cog.bot = bot
    cog.cooldowns = {}
    cog._niveaux_actifs = AsyncMock(return_value=levels_enabled)
    cog._process_xp = AsyncMock()
    return cog, bot, db


def _message(*, message_id: int = 42, bot: bool = False, guild_id: int | None = 100):
    return SimpleNamespace(
        id=message_id,
        guild=SimpleNamespace(id=guild_id) if guild_id is not None else None,
        author=SimpleNamespace(id=200, bot=bot),
        channel=SimpleNamespace(id=300),
    )


@pytest.mark.asyncio
async def test_message_count_increments_when_levels_disabled():
    cog, bot, db = _make_cog(levels_enabled=False)

    await cog.on_message(_message())

    db.execute.assert_awaited_once()
    sql, params = db.execute.await_args.args
    assert "INSERT INTO message_counts" in sql
    assert "count = count + 1" in sql
    assert params == (100, 200)
    db.get_stats_settings.assert_not_awaited()
    cog._process_xp.assert_not_awaited()


@pytest.mark.asyncio
async def test_message_count_increments_even_during_xp_cooldown():
    cog, _bot, db = _make_cog(levels_enabled=True)
    cog.cooldowns[(100, 200)] = time.time() + 120

    await cog.on_message(_message(message_id=1))
    await cog.on_message(_message(message_id=2))

    assert db.execute.await_count == 2
    cog._process_xp.assert_not_awaited()


@pytest.mark.asyncio
async def test_command_not_awarded_xp_but_still_counted():
    cog, bot, db = _make_cog(
        levels_enabled=True,
        settings={"xp_cooldown": 60, "xp_disabled_on_commands": True},
    )
    bot.get_context.return_value = SimpleNamespace(valid=True)

    await cog.on_message(_message())

    db.execute.assert_awaited_once()
    bot.get_context.assert_awaited_once()
    cog._process_xp.assert_not_awaited()


@pytest.mark.asyncio
async def test_xp_skip_ids_still_count_real_messages():
    cog, bot, db = _make_cog(levels_enabled=True)
    bot._xp_skip_ids = {42}

    await cog.on_message(_message())

    db.execute.assert_awaited_once()
    cog._process_xp.assert_not_awaited()


@pytest.mark.asyncio
async def test_ignored_bot_messages_and_dm_do_not_count():
    cog, _bot, db = _make_cog(levels_enabled=False)
    await cog.on_message(_message(bot=True))
    await cog.on_message(_message(guild_id=None))

    db.execute.assert_not_awaited()
    cog._niveaux_actifs.assert_not_awaited()


@pytest.mark.asyncio
async def test_xp_handler_does_not_count_the_message_again():
    cog, _bot, db = _make_cog(levels_enabled=True)
    cog._apply_xp_delta = AsyncMock(return_value=(8, 0, False))
    with patch("cogs.levels.temporary_boosts.apply_xp_boost", new_callable=AsyncMock) as boost:
        boost.return_value = (8, None)
        # Tester le chemin métier réel, pas le faux _process_xp utilisé par les
        # autres tests pour empêcher l'exécution de tâches en arrière-plan.
        await Levels._process_xp(cog, _message(), {"xp_min": 8, "xp_max": 8}, None)

    db.execute.assert_not_awaited()
    cog._apply_xp_delta.assert_awaited_once_with(100, 200, 8)


@pytest.mark.asyncio
async def test_failure_to_count_does_not_block_other_listeners_or_xp():
    cog, _bot, db = _make_cog(levels_enabled=True)
    db.execute.side_effect = RuntimeError("SQLite temporairement occupée")
    with patch.object(cog, "_process_xp", new_callable=AsyncMock) as process:
        await cog.on_message(_message())
        await asyncio.sleep(0)

    db.execute.assert_awaited_once()
    process.assert_awaited_once()
