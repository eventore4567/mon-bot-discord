"""Contrats du journal Soundboard.

Ces tests sont volontairement sans réseau Discord. Ils verrouillent le routage, la
compatibilité des anciennes configurations et les quatre listeners introduits par le cog.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "x")

import pytest  # noqa: E402

from cogs.soundboard_logs import SoundboardLogs  # noqa: E402
from utils import log_service  # noqa: E402
from utils.log_categories import (  # noqa: E402
    CATEGORIES,
    category_for,
    legacy_to_category,
)


def run(coro):
    return asyncio.run(coro)


class FakeGuild:
    def __init__(self, guild_id: int = 42, *, can_audit: bool = False):
        self.id = guild_id
        self.me = SimpleNamespace(
            guild_permissions=SimpleNamespace(view_audit_log=can_audit)
        )
        self._sounds = {}

    def get_soundboard_sound(self, sound_id: int):
        return self._sounds.get(int(sound_id))


class FakeSound:
    def __init__(
        self,
        guild,
        *,
        sound_id: int = 1234,
        name: str = "Airhorn",
        emoji=None,
        volume: float = 1.0,
        user=None,
    ):
        self.guild = guild
        self.id = sound_id
        self.name = name
        self.emoji = emoji
        self.volume = volume
        self.user = user


@pytest.mark.parametrize(
    "event",
    ["soundboard_create", "soundboard_update", "soundboard_delete", "soundboard_play"],
)
def test_soundboard_events_use_one_dedicated_category(event):
    assert CATEGORIES["soundboard"] == "Soundboard"
    assert category_for(event) == "soundboard"


def test_legacy_alias_is_additive_and_needs_no_guild_config_column():
    assert legacy_to_category("log_soundboard") == "soundboard"
    # Soundboard utilise log_config. Une ancienne ligne guild_config ne doit donc ni
    # posséder ni exiger une nouvelle colonne lors du déploiement.
    assert "soundboard" not in log_service._LEGACY_COLUMNS


def test_disabled_soundboard_route_is_a_safe_noop(monkeypatch):
    async def disabled(*_args, **_kwargs):
        return {"channel_id": 999, "enabled": False, "updated_at": 0}

    monkeypatch.setattr(log_service, "get_log_config", disabled)
    ok, message = run(
        log_service.send_test_log(
            object(), FakeGuild(), "soundboard", SimpleNamespace(id=7)
        )
    )
    assert ok is False
    assert "désactivée" in message


def test_missing_audit_permission_never_touches_audit_logs():
    guild = FakeGuild(can_audit=False)
    cog = SoundboardLogs(object())
    assert run(cog._audit_actor(guild, "soundboard_sound_create", 1234)) == (None, None)


def test_sound_create_emits_once_without_audit_permission():
    guild = FakeGuild()
    uploader = SimpleNamespace(id=91)
    sound = FakeSound(guild, user=uploader)
    cog = SoundboardLogs(object())
    cog._audit_actor = AsyncMock(return_value=(None, None))
    cog._send = AsyncMock(return_value=True)

    run(cog.on_soundboard_sound_create(sound))

    cog._send.assert_awaited_once()
    args = cog._send.await_args.args
    assert args[0] is guild
    assert args[1] == "soundboard_create"
    assert args[2].title == "Son Soundboard ajouté"


def test_sound_update_only_logs_real_changes():
    guild = FakeGuild()
    before = FakeSound(guild, name="Airhorn", volume=1.0)
    after = FakeSound(guild, name="Airhorn 2", volume=0.5)
    cog = SoundboardLogs(object())
    cog._audit_actor = AsyncMock(return_value=(None, None))
    cog._send = AsyncMock(return_value=True)

    run(cog.on_soundboard_sound_update(before, after))

    cog._send.assert_awaited_once()
    args = cog._send.await_args.args
    assert args[1] == "soundboard_update"
    field_names = {field.name for field in args[2].fields}
    assert {"Nom", "Volume"} <= field_names


def test_sound_update_unchanged_object_is_ignored():
    guild = FakeGuild()
    before = FakeSound(guild)
    after = FakeSound(guild)
    cog = SoundboardLogs(object())
    cog._audit_actor = AsyncMock(return_value=(None, None))
    cog._send = AsyncMock(return_value=True)

    run(cog.on_soundboard_sound_update(before, after))

    cog._send.assert_not_awaited()
    cog._audit_actor.assert_not_awaited()


def test_sound_delete_emits_once():
    guild = FakeGuild()
    sound = FakeSound(guild)
    cog = SoundboardLogs(object())
    cog._audit_actor = AsyncMock(return_value=(None, None))
    cog._send = AsyncMock(return_value=True)

    run(cog.on_soundboard_sound_delete(sound))

    cog._send.assert_awaited_once()
    assert cog._send.await_args.args[1] == "soundboard_delete"


def test_voice_effect_logs_real_sound_play_with_user_and_channel():
    guild = FakeGuild()
    guild._sounds[1234] = FakeSound(guild, name="Airhorn")
    channel = SimpleNamespace(id=555, guild=guild)
    effect = SimpleNamespace(
        channel=channel,
        user=SimpleNamespace(id=77),
        sound=SimpleNamespace(id=1234, volume=0.75),
    )
    cog = SoundboardLogs(object())
    cog._send = AsyncMock(return_value=True)

    run(cog.on_voice_channel_effect(effect))

    cog._send.assert_awaited_once()
    args = cog._send.await_args.args
    assert args[1] == "soundboard_play"
    fields = {field.name: field.value for field in args[2].fields}
    assert fields["Son"] == "`Airhorn`"
    assert fields["Utilisateur"] == "<@77>"
    assert fields["Salon vocal"] == "<#555>"


def test_voice_effect_without_sound_is_not_faked():
    guild = FakeGuild()
    effect = SimpleNamespace(
        channel=SimpleNamespace(id=555, guild=guild),
        user=SimpleNamespace(id=77),
        sound=None,
    )
    cog = SoundboardLogs(object())
    cog._send = AsyncMock(return_value=True)

    run(cog.on_voice_channel_effect(effect))

    cog._send.assert_not_awaited()
