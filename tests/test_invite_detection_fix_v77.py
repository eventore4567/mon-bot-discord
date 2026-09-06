from __future__ import annotations

import asyncio
from types import SimpleNamespace

from cogs import invite_detection_fix_v77 as v77


class FakeInvite:
    def __init__(self, code: str, *, uses: int = 0, max_uses: int = 0, inviter_id: int | None = None, guild=None):
        self.code = code
        self.uses = uses
        self.max_uses = max_uses
        self.inviter = SimpleNamespace(id=inviter_id) if inviter_id is not None else None
        self.guild = guild


class FakeGuild:
    def __init__(self, guild_id: int, snapshots):
        self.id = guild_id
        self._snapshots = list(snapshots)
        self._index = 0

    async def invites(self):
        if not self._snapshots:
            return []
        index = min(self._index, len(self._snapshots) - 1)
        self._index += 1
        return list(self._snapshots[index])


class FakeInvitesCog:
    def __init__(self):
        self.invite_cache = {}

    async def find_used_invite(self, guild):
        return None

    async def _invitation_vanity(self, guild):
        return None


class FakeBot:
    def __init__(self, cog):
        self.cog = cog
        self.listeners = {}

    def get_cog(self, name):
        return self.cog if name == "Invites" else None

    def add_listener(self, callback, name):
        self.listeners[name] = callback


def _without_retry_delays():
    old = v77._RETRY_DELAYS
    v77._RETRY_DELAYS = (0.0,)
    return old


def test_v77_keeps_normal_invite_counter_detection():
    guild = FakeGuild(1, [[]])
    invite = FakeInvite("normal", uses=2, inviter_id=42, guild=guild)
    guild._snapshots = [[invite]]
    cog = FakeInvitesCog()
    cog.invite_cache = {1: {"normal": 1}}
    bot = FakeBot(cog)

    old = _without_retry_delays()
    try:
        assert v77.install(bot)
        result = asyncio.run(cog.find_used_invite(guild))
    finally:
        v77._RETRY_DELAYS = old

    assert result is invite
    assert result.inviter.id == 42


def test_v77_recovers_one_use_invite_deleted_before_member_join():
    guild = FakeGuild(2, [[]])
    consumed = FakeInvite("once", uses=1, max_uses=1, inviter_id=99, guild=guild)
    cog = FakeInvitesCog()
    cog.invite_cache = {2: {"once": 0}}
    bot = FakeBot(cog)

    old = _without_retry_delays()
    try:
        assert v77.install(bot)
        asyncio.run(bot.listeners["on_invite_delete"](consumed))
        result = asyncio.run(cog.find_used_invite(guild))
    finally:
        v77._RETRY_DELAYS = old

    assert result is consumed
    assert result.inviter.id == 99


def test_v77_never_guesses_between_two_recent_deleted_invites():
    guild = FakeGuild(3, [[]])
    first = FakeInvite("a", uses=1, max_uses=1, inviter_id=10, guild=guild)
    second = FakeInvite("b", uses=1, max_uses=1, inviter_id=11, guild=guild)
    cog = FakeInvitesCog()
    bot = FakeBot(cog)

    old = _without_retry_delays()
    try:
        assert v77.install(bot)
        asyncio.run(bot.listeners["on_invite_delete"](first))
        asyncio.run(bot.listeners["on_invite_delete"](second))
        result = asyncio.run(cog.find_used_invite(guild))
    finally:
        v77._RETRY_DELAYS = old

    assert result is None


def test_v77_only_uses_plausibly_consumed_limited_invites():
    guild = SimpleNamespace(id=4)
    assert v77._plausibly_consumed(FakeInvite("once", uses=0, max_uses=1, inviter_id=1, guild=guild))
    assert v77._plausibly_consumed(FakeInvite("five", uses=5, max_uses=5, inviter_id=1, guild=guild))
    assert not v77._plausibly_consumed(FakeInvite("manual", uses=0, max_uses=0, inviter_id=1, guild=guild))
    assert not v77._plausibly_consumed(FakeInvite("not-full", uses=2, max_uses=5, inviter_id=1, guild=guild))
