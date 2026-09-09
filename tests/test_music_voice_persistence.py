from __future__ import annotations

from types import SimpleNamespace

import pytest

from sentrix_music_voice_persistence import PersistentVoiceState


class FakeDB:
    def __init__(self):
        self.rows: dict[int, dict] = {}

    async def execute(self, query: str, params: tuple = ()):
        normalized = " ".join(query.split()).upper()
        if normalized.startswith("CREATE TABLE"):
            return None
        if normalized.startswith("INSERT INTO MUSIC_VOICE_SESSIONS"):
            guild_id, voice_channel_id, text_channel_id, updated_at = params
            self.rows[int(guild_id)] = {
                "guild_id": int(guild_id),
                "voice_channel_id": int(voice_channel_id),
                "text_channel_id": int(text_channel_id) if text_channel_id is not None else None,
                "updated_at": int(updated_at),
            }
            return None
        if normalized.startswith("DELETE FROM MUSIC_VOICE_SESSIONS"):
            self.rows.pop(int(params[0]), None)
            return None
        raise AssertionError(f"requête inattendue: {query}")

    async def fetchone(self, query: str, params: tuple = ()):
        row = self.rows.get(int(params[0]))
        if row is None:
            return None
        if "SELECT 1" in query.upper():
            return {"1": 1}
        return dict(row)

    async def fetchall(self, query: str, params: tuple = ()):
        assert "MUSIC_VOICE_SESSIONS" in query.upper()
        return [dict(row) for _, row in sorted(self.rows.items())]


class FakeVoiceClient:
    def __init__(self, channel):
        self.channel = channel

    def is_connected(self):
        return True


class FakeVoiceChannel:
    def __init__(self, channel_id: int):
        self.id = channel_id
        self.connect_calls = 0

    async def connect(self, *, timeout: int, reconnect: bool):
        assert timeout == 30
        assert reconnect is True
        self.connect_calls += 1
        return FakeVoiceClient(self)


class FakeGuild:
    def __init__(self, guild_id: int, channel: FakeVoiceChannel):
        self.id = guild_id
        self._channel = channel
        self.voice_client = None

    def get_channel(self, channel_id: int):
        return self._channel if channel_id == self._channel.id else None


class FakeCog:
    def __init__(self):
        self.queues = {}

    def get_queue(self, guild_id: int):
        if guild_id not in self.queues:
            self.queues[guild_id] = SimpleNamespace(
                guild_id=guild_id,
                voice_client=None,
                text_channel=None,
            )
        return self.queues[guild_id]


class FakeBot:
    def __init__(self, guild: FakeGuild | None = None):
        self.db = FakeDB()
        self._guild = guild
        self.user = SimpleNamespace(id=999)
        self.sentrix_durable_store = None

    def is_ready(self):
        return True

    def is_closed(self):
        return False

    def get_guild(self, guild_id: int):
        if self._guild and self._guild.id == guild_id:
            return self._guild
        return None


@pytest.mark.asyncio
async def test_voice_pin_survives_external_disconnect_until_explicit_forget():
    bot = FakeBot()
    cog = FakeCog()
    state = PersistentVoiceState(bot, cog)

    await state.remember(123, 456, 789)
    assert await state.is_pinned(123) is True

    # Une coupure Discord/Railway ne vaut jamais /music leave.
    member = SimpleNamespace(id=999, guild=SimpleNamespace(id=123))
    await state.on_voice_state_update(
        member,
        SimpleNamespace(channel=SimpleNamespace(id=456)),
        SimpleNamespace(channel=None),
    )
    assert await state.is_pinned(123) is True

    await state.forget(123)
    assert await state.is_pinned(123) is False


@pytest.mark.asyncio
async def test_restore_all_rejoins_pinned_voice_channel_after_restart():
    channel = FakeVoiceChannel(456)
    guild = FakeGuild(123, channel)
    bot = FakeBot(guild)
    cog = FakeCog()
    state = PersistentVoiceState(bot, cog)

    await state.remember(123, 456, None)
    await state.restore_all()

    queue = cog.get_queue(123)
    assert channel.connect_calls == 1
    assert queue.voice_client is not None
    assert queue.voice_client.is_connected() is True
    assert queue.voice_client.channel.id == 456


@pytest.mark.asyncio
async def test_restore_keeps_pin_when_connection_temporarily_fails():
    class FailingChannel(FakeVoiceChannel):
        async def connect(self, *, timeout: int, reconnect: bool):
            self.connect_calls += 1
            raise RuntimeError("Discord temporairement indisponible")

    channel = FailingChannel(456)
    guild = FakeGuild(123, channel)
    bot = FakeBot(guild)
    cog = FakeCog()
    state = PersistentVoiceState(bot, cog)

    await state.remember(123, 456, None)
    await state.restore_all()

    assert channel.connect_calls == 1
    assert await state.is_pinned(123) is True


def test_runtime_contract_has_no_inactivity_leave_and_unpins_only_on_music_leave():
    source = open("sentrix_music_voice_persistence.py", encoding="utf-8").read()
    assert "_never_disconnect_for_inactivity" in source
    assert "cog._schedule_disconnect =" in source
    assert 'bot.get_command("music leave")' in source
    assert "await state.forget(int(ctx.guild.id))" in source
    assert "reconnexion après restart/failover jusqu'à /music leave" in source


def test_v104_is_installed_by_real_music_loader():
    source = open("sentrix_music_providers_v102.py", encoding="utf-8").read()
    assert "from sentrix_music_voice_persistence import install_on_cog" in source
    assert "install_on_cog(bot, cog)" in source
    assert "V102/V103/V104" in source
