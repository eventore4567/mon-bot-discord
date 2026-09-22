from __future__ import annotations

import asyncio
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils.failover import SentriXFailoverCoordinator


class _FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    async def get(self, key):
        return self.data.get(key)

    async def eval(self, script, _n, key, owner, *args):
        if self.data.get(key) != owner:
            return 0
        if "del" in script:
            self.data.pop(key, None)
        return 1

    async def aclose(self):
        return None


def _coordinator(service: str, redis: _FakeRedis, role: str):
    coord = SentriXFailoverCoordinator()
    coord.enabled = True
    coord.redis_url = "redis://fake"
    coord.service_id = service
    coord.role = role
    coord.state = "starting"
    coord.previous_state = None
    coord.transition_count = 0
    coord._redis = redis
    return coord


async def _scenario():
    redis = _FakeRedis()

    primary = _coordinator("mon-bot-discord", redis, "primary")
    assert await primary._try_acquire() is True
    health = primary.health()
    assert health["state"] == "leader"
    assert health["previous_state"] == "starting"
    assert health["last_transition_reason"] == "initial_lease_acquire"
    assert health["transition_count"] == 1
    assert health["last_transition_at"] > 0
    assert health["leader_is_standby"] is False

    assert await primary.release() is True
    released = primary.health()
    assert released["state"] == "released"
    assert released["previous_state"] == "leader"
    assert released["last_transition_reason"] == "lease_released"

    same_primary = _coordinator("mon-bot-discord", redis, "primary")
    assert await same_primary._try_acquire() is True
    assert same_primary.health()["last_transition_reason"] == "same_service_restart"
    await same_primary.release()

    standby = _coordinator("sentrix-standby", redis, "standby")
    assert await standby._try_acquire() is True
    takeover = standby.health()
    assert takeover["last_transition_reason"] == "takeover_from:mon-bot-discord"
    assert takeover["leader_is_standby"] is True


def test_ha_health_exposes_transition_reason_time_and_standby_leader():
    asyncio.run(_scenario())


async def _waiting_scenario():
    redis = _FakeRedis()
    leader = _coordinator("mon-bot-discord", redis, "primary")
    await leader._try_acquire()

    waiting = _coordinator("sentrix-standby", redis, "standby")
    assert await waiting._try_acquire() is False
    health = waiting.health()
    assert health["state"] == "standby"
    assert health["last_transition_reason"] == "lease_held_by_other"
    assert health["leader"] is False
    assert health["current_owner"] == leader.owner_id


def test_passive_instance_reports_why_it_is_waiting():
    asyncio.run(_waiting_scenario())


def test_transition_helper_counts_state_changes_and_keeps_previous_state():
    coord = SentriXFailoverCoordinator()
    coord.state = "starting"
    coord.previous_state = None
    coord.transition_count = 0

    coord._transition("standby", "lease_held_by_other")
    first_time = coord.last_transition_at
    coord._transition("blocked", "redis_unavailable")

    assert coord.previous_state == "standby"
    assert coord.state == "blocked"
    assert coord.transition_count == 2
    assert coord.last_transition_reason == "redis_unavailable"
    assert coord.last_transition_at >= first_time

def test_same_passive_poll_does_not_create_a_fake_transition():
    coord = SentriXFailoverCoordinator()
    coord.state = "standby"
    coord.previous_state = "starting"
    coord.last_transition_reason = "lease_held_by_other"
    coord.transition_count = 1
    original_time = coord.last_transition_at

    coord._transition("standby", "lease_held_by_other")

    assert coord.transition_count == 1
    assert coord.previous_state == "starting"
    assert coord.last_transition_at == original_time

