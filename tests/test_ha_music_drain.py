import asyncio
from types import SimpleNamespace

import sentrix_ha_music_drain as drain
from utils.failover import SentriXFailoverCoordinator


class FakeVoice:
    def __init__(self, *, connected=True, playing=False, paused=False):
        self.connected = connected
        self.playing = playing
        self.paused = paused

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return self.playing

    def is_paused(self):
        return self.paused


class FakeBot:
    def __init__(self, voice_clients=(), queues=None):
        self.voice_clients = list(voice_clients)
        self._music = SimpleNamespace(queues=queues or {})

    def get_cog(self, name):
        return self._music if name == "Music" else None


class FakeRedis:
    def __init__(self, waiting=True):
        self.waiting = waiting

    async def get(self, _key):
        return "primary-owner" if self.waiting else None


def make_coordinator(bot, *, waiting=True):
    coordinator = SentriXFailoverCoordinator.__new__(SentriXFailoverCoordinator)
    coordinator._redis = FakeRedis(waiting)
    coordinator.attente_primary_key = "test:primary-waiting"
    coordinator._sentrix_watchdog_bot = bot
    coordinator._sentrix_music_handoff_deferred = False
    return coordinator


def test_playing_voice_blocks_planned_handoff():
    bot = FakeBot([FakeVoice(playing=True)])
    assert drain.music_activity_blocks_handoff(bot) is True


def test_paused_voice_blocks_planned_handoff():
    bot = FakeBot([FakeVoice(paused=True)])
    assert drain.music_activity_blocks_handoff(bot) is True


def test_idle_voice_does_not_block_handoff():
    bot = FakeBot([FakeVoice()])
    assert drain.music_activity_blocks_handoff(bot) is False


def test_connected_music_queue_blocks_even_between_tracks():
    vc = FakeVoice()
    queue = SimpleNamespace(voice_client=vc, current=None, tracks=[object()])
    bot = FakeBot([vc], queues={123: queue})
    assert drain.music_activity_blocks_handoff(bot) is True


def test_disconnected_stale_queue_does_not_block_handoff():
    vc = FakeVoice(connected=False)
    queue = SimpleNamespace(voice_client=vc, current=object(), tracks=[object()])
    bot = FakeBot([], queues={123: queue})
    assert drain.music_activity_blocks_handoff(bot) is False


def test_primary_waiting_is_deferred_while_music_active():
    coordinator = make_coordinator(FakeBot([FakeVoice(playing=True)]), waiting=True)
    result = asyncio.run(drain._primary_waiting_drain_aware(coordinator))
    assert result is False
    assert coordinator._sentrix_music_handoff_deferred is True


def test_primary_waiting_is_allowed_when_music_idle():
    coordinator = make_coordinator(FakeBot([FakeVoice()]), waiting=True)
    coordinator._sentrix_music_handoff_deferred = True
    result = asyncio.run(drain._primary_waiting_drain_aware(coordinator))
    assert result is True
    assert coordinator._sentrix_music_handoff_deferred is False


def test_no_primary_waiting_never_blocks_lease_watchdog():
    coordinator = make_coordinator(FakeBot([FakeVoice(playing=True)]), waiting=False)
    coordinator._sentrix_music_handoff_deferred = True
    result = asyncio.run(drain._primary_waiting_drain_aware(coordinator))
    assert result is False
    assert coordinator._sentrix_music_handoff_deferred is False


def test_install_does_not_touch_emergency_renew_path():
    original_renew = SentriXFailoverCoordinator._renew_once
    drain.install()
    assert SentriXFailoverCoordinator._renew_once is original_renew
