from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
import pytest

from cogs.music import GuildMusicQueue, Music, MusicControlsModal
from utils.music import Track, ResolvedRequest
from utils import sentrix_panels as panels
from test_music_cog import _FakeVoiceClient, _FakeVoiceChannel


def _music():
    music = Music.__new__(Music)
    music.bot = SimpleNamespace()
    music.queues = {}
    music._player_messages = {}
    music._player_activity = {}
    return music


def _interaction(channel_id=10):
    state = {"done": False}
    async def defer(**_kwargs):
        state["done"] = True
    return SimpleNamespace(
        guild_id=1, guild=SimpleNamespace(id=1, voice_client=None),
        user=SimpleNamespace(id=5, voice=SimpleNamespace(channel=SimpleNamespace(id=channel_id))),
        response=SimpleNamespace(is_done=lambda: state["done"], defer=AsyncMock(side_effect=defer), send_message=AsyncMock(), send_modal=AsyncMock(), edit_message=AsyncMock()),
        edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()),
    )


def _active(music):
    queue = music.get_queue(1)
    voice = _FakeVoiceClient(_FakeVoiceChannel(10))
    voice._playing = True
    queue.voice_client = voice
    queue.current = Track(title="Faded", artist="Alan Walker", duration=212, requested_by=5)
    return queue


def _button(panel, name):
    return next(button for button in panel.boutons_source if button.custom_id.endswith(":" + name))


@pytest.mark.asyncio
async def test_pause_and_resume_update_real_audio_clock_and_same_message():
    music = _music()
    queue = _active(music)
    panel = music._music_player_panel(queue)
    interaction = _interaction()
    await _button(panel, "pause").callback(interaction)
    assert queue.paused_by_user and queue.voice_client.is_paused()
    interaction.response.defer.assert_awaited_once()
    refreshed = interaction.edit_original_response.await_args.kwargs["view"]
    assert refreshed.titre == "⏸️ Lecture en pause"
    assert _button(refreshed, "pause").libelle == "Reprendre"
    await _button(refreshed, "pause").callback(_interaction())
    assert not queue.paused_by_user and queue.voice_client.is_playing()


@pytest.mark.asyncio
async def test_new_controls_really_toggle_autoplay_and_cycle_loop_modes():
    music = _music()
    queue = _active(music)
    await _button(music._music_player_panel(queue), "autoplay").callback(_interaction())
    assert queue.autoplay
    for state in [(True, False), (False, True), (False, False)]:
        await _button(music._music_player_panel(queue), "loop").callback(_interaction())
        assert (queue.loop_track, queue.loop_queue) == state


@pytest.mark.asyncio
@pytest.mark.parametrize("command,args", [("music_volume", (90,)), ("music_loop", ("queue",)), ("music_shuffle", ()), ("music_remove", (1,)), ("music_clear", ()), ("music_autoplay", ())])
async def test_commands_cannot_mutate_queue_from_another_voice_channel(command, args):
    music = _music()
    queue = _active(music)
    queue.tracks = [Track(title="A"), Track(title="B")]
    ctx = SimpleNamespace(guild=SimpleNamespace(id=1), author=_interaction(999).user, interaction=None)
    with patch.object(panels, "texte_court", AsyncMock()) as reply:
        await getattr(Music, command).callback(music, ctx, *args)
    assert queue.volume == 0.5
    assert not queue.loop_track and not queue.loop_queue and not queue.autoplay
    assert [t.title for t in queue.tracks] == ["A", "B"]
    reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_idle_player_can_open_search_without_already_connected_bot():
    music = _music()
    panel = music._music_player_panel(music.get_queue(1))
    interaction = _interaction()
    await _button(panel, "add").callback(interaction)
    interaction.response.send_modal.assert_awaited_once()
    assert _button(panel, "pause").desactive
    assert not _button(panel, "add").desactive


@pytest.mark.asyncio
async def test_queue_pagination_can_reach_last_track():
    music = _music()
    queue = music.get_queue(1)
    queue.tracks = [Track(title=f"Title {i}") for i in range(1, 20)]
    panel = music._music_queue_panel(queue, 1)
    interaction = _interaction()
    await panel.boutons_source[1].callback(interaction)
    last = interaction.response.edit_message.await_args.kwargs["view"]
    text = "\n".join(section.rendu() for section in last.sections_source)
    assert "Title 19" in text and "3/3" in last.sous_titre
    assert last.boutons_source[1].desactive


@pytest.mark.asyncio
async def test_invalid_modal_changes_neither_audio_nor_volume():
    music = _music()
    queue = _active(music)
    modal = MusicControlsModal(music, 1)
    modal.volume_input._value = "85"
    modal.position_input._value = "8:00"  # track only lasts 3:32
    interaction = _interaction()
    await modal.on_submit(interaction)
    assert queue.volume == 0.5
    interaction.response.send_message.assert_awaited_once()
    interaction.response.defer.assert_not_awaited()


@pytest.mark.asyncio
async def test_modal_applies_volume_and_parsed_position_to_real_methods():
    music = _music()
    queue = _active(music)
    music._seek_queue = AsyncMock(return_value=True)
    modal = MusicControlsModal(music, 1)
    modal.volume_input._value = "70"
    modal.position_input._value = "1:30"
    interaction = _interaction()
    await modal.on_submit(interaction)
    music._seek_queue.assert_awaited_once_with(queue, 90)
    assert queue.volume == 0.7
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_seek_preserves_pause_and_uses_playback_transition_lock():
    music = _music()
    queue = _active(music)
    music._pause_queue(queue)
    async def play(q, track, **kwargs):
        assert q.advance_lock.locked()
        q.voice_client._playing = True
        return True
    music._play_track = play
    assert await music._seek_queue(queue, 90)
    assert queue.paused_by_user and queue.voice_client.is_paused()


@pytest.mark.asyncio
async def test_player_stays_within_discord_component_limits():
    music = _music()
    panel = music._music_player_panel(_active(music))
    assert panel.total_children_count <= 40
    assert len(panel.boutons_source) == 10
    assert all(callable(b.callback) for b in panel.boutons_source)


@pytest.mark.asyncio
async def test_empty_provider_result_gets_clear_answer_instead_of_index_error():
    music = _music()
    queue = _active(music)
    music._ensure_voice = AsyncMock(return_value=queue)
    music.manager = SimpleNamespace(resolve=AsyncMock(return_value=ResolvedRequest(tracks=[])))
    ctx = SimpleNamespace(guild=SimpleNamespace(id=1), author=SimpleNamespace(id=5), interaction=None)
    with patch.object(panels, "texte_court", AsyncMock()) as reply:
        await music._resolve_and_queue(ctx, "titre absent")
    assert "Aucun titre jouable" in reply.await_args.args[1]


@pytest.mark.asyncio
async def test_play_cannot_move_bot_away_from_another_active_voice():
    music = _music()
    queue = _active(music)
    music.get_system_settings = AsyncMock(return_value={"configured": False})
    music._cancel_disconnect = Mock()
    ctx = SimpleNamespace(guild=SimpleNamespace(id=1, voice_client=queue.voice_client),
                          author=_interaction(999).user, channel=SimpleNamespace(), interaction=None)
    ctx.author.voice.channel.connect = AsyncMock()
    with patch.object(panels, "texte_court", AsyncMock()):
        assert await music._ensure_voice(ctx) is None
    assert queue.voice_client.channel.id == 10
    assert queue.voice_client.move_calls == 0


@pytest.mark.asyncio
async def test_music_can_be_disabled_after_configured_voice_was_deleted():
    music = _music()
    music.shutdown_guild_music = AsyncMock()
    guild = SimpleNamespace(id=1, me=None, get_channel=lambda _id: None)
    with patch("cogs.music.save_music_settings", AsyncMock(return_value={"enabled": False})) as save:
        result = await music.configure_system(guild, enabled=False, voice_channel_id=999)
    assert not result["enabled"]
    save.assert_awaited_once()
    music.shutdown_guild_music.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_stop_waits_for_in_flight_seek_instead_of_racing_playback():
    import asyncio
    music = _music()
    queue = _active(music)
    queue.tracks = [Track(title="Next")]
    await queue.advance_lock.acquire()
    task = asyncio.create_task(music._stop_queue(queue))
    try:
        await asyncio.sleep(0)
        assert queue.current is not None and queue.tracks
        assert not task.done()
    finally:
        queue.advance_lock.release()
        await task
    assert queue.current is None and not queue.tracks
    assert not queue.voice_client.is_playing()


@pytest.mark.asyncio
async def test_member_players_are_tracked_separately():
    music = _music()
    queue = music.get_queue(1)
    first = SimpleNamespace(id=11, channel=SimpleNamespace(id=10), edit=AsyncMock())
    second = SimpleNamespace(id=12, channel=SimpleNamespace(id=10), edit=AsyncMock())
    with patch.object(panels, 'envoyer', AsyncMock(side_effect=[first, second])):
        await music._show_player(object(), queue)
        await music._show_player(object(), queue)
    assert len(music._player_messages) == 2


@pytest.mark.asyncio
async def test_idle_player_receives_final_update_then_stops_refreshing():
    music = _music()
    music.get_queue(1)
    message = SimpleNamespace(edit=AsyncMock())
    music._player_messages[(1, 11)] = message
    await Music._player_refresher.coro(music)
    await Music._player_refresher.coro(music)
    message.edit.assert_awaited_once()
    with patch("cogs.music.time.monotonic", return_value=music._player_activity[(1, 11)][0] + 901):
        await Music._player_refresher.coro(music)
    assert not music._player_messages
