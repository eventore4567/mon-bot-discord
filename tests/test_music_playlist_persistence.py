from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
import pytest
from discord.ext import commands

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database
from sentrix_music_playlists_v108 import (
    _fetch_playlist,
    _install_playlist_group,
    _install_schema,
    _save_items,
    decode_playlist_items,
)


def _ctx(guild_id: int, user_id: int):
    return SimpleNamespace(
        guild=SimpleNamespace(id=guild_id),
        author=SimpleNamespace(id=user_id),
        interaction=None,
        defer=AsyncMock(),
        typing=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_playlist_create_rename_delete_persists_and_isolates_users():
    tmp = tempfile.TemporaryDirectory()
    db = Database(os.path.join(tmp.name, "sentrix-playlists.db"))
    await db.connect()

    bot = commands.Bot(
        command_prefix="+",
        intents=discord.Intents.none(),
        help_command=None,
    )
    bot.db = db

    async def music_root(_ctx):
        return None

    bot.add_command(commands.Group(music_root, name="music"))
    music_cog = SimpleNamespace(_sentrix_playlists_v108=False)
    await _install_schema(bot)
    _install_playlist_group(bot, music_cog)

    create = bot.get_command("music playlist create")
    rename = bot.get_command("music playlist rename")
    delete = bot.get_command("music playlist delete")
    assert create is not None
    assert rename is not None
    assert delete is not None

    first = _ctx(100, 1)
    second = _ctx(100, 2)
    send = AsyncMock()

    try:
        with patch("sentrix_music_playlists_v108._send", new=send):
            await create.callback(first, nom="Chill")
            await create.callback(second, nom="Chill")

            row_first = await _fetch_playlist(bot, 100, 1, "chill")
            row_second = await _fetch_playlist(bot, 100, 2, "chill")
            assert row_first is not None
            assert row_second is not None

            items = [
                {
                    "title": "Faded",
                    "artist": "Alan Walker",
                    "duration": 212,
                    "provider": "spotify",
                    "query": "Alan Walker Faded",
                }
            ]
            await _save_items(bot, 100, 1, "chill", items)

            await rename.callback(
                first,
                ancien_nom="Chill",
                nouveau_nom="Night Drive",
            )

            assert await _fetch_playlist(bot, 100, 1, "chill") is None
            renamed = await _fetch_playlist(bot, 100, 1, "night drive")
            assert renamed is not None
            restored = decode_playlist_items(renamed["items_json"])
            assert restored[0]["title"] == "Faded"
            assert restored[0]["provider"] == "spotify"

            # Le meme ancien nom appartenant a l'autre utilisateur n'est jamais touche.
            assert await _fetch_playlist(bot, 100, 2, "chill") is not None

            await delete.callback(first, nom="Night Drive")
            assert await _fetch_playlist(bot, 100, 1, "night drive") is None
            assert await _fetch_playlist(bot, 100, 2, "chill") is not None
    finally:
        bot.remove_command("music")
        await db._conn.close()
        tmp.cleanup()


@pytest.mark.asyncio
async def test_playlist_duplicate_name_is_rejected_for_same_owner_only():
    tmp = tempfile.TemporaryDirectory()
    db = Database(os.path.join(tmp.name, "sentrix-playlists.db"))
    await db.connect()

    bot = commands.Bot(
        command_prefix="+",
        intents=discord.Intents.none(),
        help_command=None,
    )
    bot.db = db

    async def music_root(_ctx):
        return None

    bot.add_command(commands.Group(music_root, name="music"))
    music_cog = SimpleNamespace(_sentrix_playlists_v108=False)
    await _install_schema(bot)
    _install_playlist_group(bot, music_cog)
    create = bot.get_command("music playlist create")
    assert create is not None

    ctx = _ctx(200, 5)
    send = AsyncMock()

    try:
        with patch("sentrix_music_playlists_v108._send", new=send):
            await create.callback(ctx, nom="Chill")
            await create.callback(ctx, nom="chill")

        row = await db.fetchone(
            "SELECT COUNT(*) AS c FROM music_playlists WHERE guild_id=? AND user_id=?",
            (200, 5),
        )
        assert int(row["c"]) == 1
        assert send.await_count == 2
        assert send.await_args_list[-1].args[2] == "Playlist existante"
    finally:
        bot.remove_command("music")
        await db._conn.close()
        tmp.cleanup()
