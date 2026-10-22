from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from discord.ext import commands
import pytest

from cogs.translation import Translation, TEXTS
from services.translation import Translation as Result
from utils import sentrix_panels as panels
import sentrix_music_playlists_v108 as playlists


@pytest.mark.asyncio
async def test_translation_acknowledges_before_provider_and_updates_one_message():
    cog = Translation(SimpleNamespace())
    ctx = SimpleNamespace(guild=SimpleNamespace(id=1))
    progress = SimpleNamespace()
    with patch.object(panels, "envoyer", AsyncMock(return_value=progress)) as send, patch.object(panels, "editer", AsyncMock()) as edit:
        async def translate(*args):
            send.assert_awaited_once()
            return Result(text="Hello", target="en", source="fr"), TEXTS["fr"]
        cog._translate = translate
        await Translation.translate.callback(cog, ctx, "en", texte="Bonjour")
    edit.assert_awaited_once()
    assert edit.await_args.args[0] is progress
    assert "Hello" in panels.texte_complet(edit.await_args.args[1])


@pytest.mark.asyncio
async def test_translation_failure_replaces_waiting_message():
    cog = Translation(SimpleNamespace())
    cog._translate = AsyncMock(side_effect=RuntimeError("provider failed"))
    with patch.object(panels, "envoyer", AsyncMock(return_value=SimpleNamespace())), patch.object(panels, "editer", AsyncMock()) as edit:
        with pytest.raises(RuntimeError):
            await Translation.translate.callback(cog, SimpleNamespace(guild=None), "en", texte="Bonjour")
    assert edit.await_args.args[1].titre == "Traduction indisponible"


@pytest.mark.asyncio
async def test_playlist_destination_is_checked_before_network_resolution():
    bot = commands.Bot(command_prefix="+", intents=discord.Intents.none(), help_command=None)
    bot.db = SimpleNamespace(fetchone=AsyncMock(return_value=None))
    async def root(ctx):
        pass
    bot.add_command(commands.Group(root, name="music"))
    music = SimpleNamespace(_sentrix_playlists_v108=False, manager=SimpleNamespace(resolve=AsyncMock()))
    playlists._install_playlist_group(bot, music)
    ctx = SimpleNamespace(guild=SimpleNamespace(id=1), author=SimpleNamespace(id=2), interaction=None)
    try:
        with patch.object(playlists, "_send", AsyncMock()) as reply:
            await bot.get_command("music playlist add").callback(ctx, "absente", recherche="recherche réseau")
        music.manager.resolve.assert_not_awaited()
        assert reply.await_args.args[2] == "Playlist introuvable"
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_panel_edits_do_not_ping_translated_or_quoted_mentions():
    message = SimpleNamespace(edit=AsyncMock())
    await panels.editer(message, panels.Panneau(titre="Test", sous_titre="@everyone <@123>", banniere=False))
    mentions = message.edit.await_args.kwargs["allowed_mentions"]
    assert mentions.everyone is False and mentions.roles is False and mentions.users is False
