from __future__ import annotations

import asyncio
import gzip
import hashlib
import sqlite3
import time

from utils import failover
from utils.durable_database import DurableDatabaseReplica


class FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.closed = False

    async def ping(self):
        return True

    async def set(self, key, value, *, ex=None, nx=False):
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script, _count, key, holder, *args):
        del args
        if self.values.get(key) != holder:
            return 0
        if "expire" in script:
            return 1
        self.values.pop(key, None)
        return 1

    async def aclose(self):
        self.closed = True


class FakeSnapshotPool:
    def __init__(self, row):
        self.row = row

    async def fetchrow(self, *_args):
        return self.row


def settings(role="auto"):
    return failover.FailoverSettings(
        enabled=True,
        role=role,
        lease_ttl=20,
        renew_interval=5,
        poll_interval=3,
        standby_delay=8,
        snapshot_interval=30,
    )


def test_exactly_one_process_can_acquire_the_lease(monkeypatch):
    monkeypatch.setenv("SENTRIX_FAILOVER_ENABLED", "1")
    redis = FakeRedis()
    first = failover.RedisFailoverLease(settings(), redis_client=redis)
    second = failover.RedisFailoverLease(settings(), redis_client=redis)

    async def scenario():
        await first.connect()
        await second.connect()
        assert await first.try_acquire() is True
        assert await second.try_acquire() is False
        assert first.owns_lease is True
        assert second.owns_lease is False
        assert failover.is_active_process() is True

        await first.release()
        assert failover.is_active_process() is False
        assert await second.try_acquire() is True
        assert failover.is_active_process() is True
        await second.release()

    asyncio.run(scenario())


def test_renew_cannot_reclaim_a_lease_owned_by_another_process(monkeypatch):
    monkeypatch.setenv("SENTRIX_FAILOVER_ENABLED", "1")
    redis = FakeRedis()
    lease = failover.RedisFailoverLease(settings(), redis_client=redis)

    async def scenario():
        await lease.connect()
        assert await lease.try_acquire() is True
        redis.values[lease.key] = "another-process"
        assert await lease.renew() is False
        assert lease.owns_lease is False
        assert lease.status == "lease_lost"
        assert failover.is_active_process() is False

    asyncio.run(scenario())


def test_watchdog_closes_runtime_immediately_after_confirmed_lease_loss(monkeypatch):
    monkeypatch.setenv("SENTRIX_FAILOVER_ENABLED", "1")
    redis = FakeRedis()
    fast = failover.FailoverSettings(
        enabled=True,
        role="auto",
        lease_ttl=2,
        renew_interval=0.01,
        poll_interval=1,
        standby_delay=0,
        snapshot_interval=10,
    )
    lease = failover.RedisFailoverLease(fast, redis_client=redis)
    closed = False

    async def close_runtime():
        nonlocal closed
        closed = True

    async def scenario():
        await lease.connect()
        assert await lease.try_acquire() is True
        redis.values[lease.key] = "another-process"
        await asyncio.wait_for(lease.maintain(close_runtime), timeout=1)
        assert closed is True
        assert lease.owns_lease is False

    asyncio.run(scenario())


def test_failover_disabled_preserves_single_service_runtime(monkeypatch):
    monkeypatch.setenv("SENTRIX_FAILOVER_ENABLED", "0")
    failover.install_active_coordinator(None)
    assert failover.is_active_process() is True


def test_environment_settings_are_bounded(monkeypatch):
    monkeypatch.setenv("SENTRIX_FAILOVER_ENABLED", "yes")
    monkeypatch.setenv("SENTRIX_FAILOVER_ROLE", "standby")
    monkeypatch.setenv("SENTRIX_FAILOVER_LEASE_TTL", "2")
    monkeypatch.setenv("SENTRIX_FAILOVER_RENEW_INTERVAL", "99")
    monkeypatch.setenv("SENTRIX_FAILOVER_SNAPSHOT_INTERVAL", "1")
    value = failover.FailoverSettings.from_env()
    assert value.enabled is True
    assert value.role == "standby"
    assert value.lease_ttl == 12
    assert value.renew_interval == 4
    assert value.snapshot_interval == 10


def test_public_state_never_exposes_redis_url(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://secret-password@redis.internal:6379")
    lease = failover.RedisFailoverLease(settings(), redis_client=FakeRedis())
    rendered = repr(lease.public_state())
    assert "secret-password" not in rendered
    assert "redis.internal" not in rendered


def test_promoted_standby_receives_all_unique_runtime_authorities(monkeypatch):
    monkeypatch.setenv("SENTRIX_FAILOVER_ENABLED", "1")
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "sentrix-failover")
    redis = FakeRedis()
    lease = failover.RedisFailoverLease(settings("standby"), redis_client=redis)

    async def scenario():
        await lease.connect()
        assert await lease.try_acquire() is True

        from cogs import (
            log_rectangle_v25,
            passive_ai_single_reply_final,
            production_alert_noise_fix,
        )
        from utils import log_service

        assert log_rectangle_v25._is_primary_process() is True
        assert passive_ai_single_reply_final._is_primary_service() is True
        assert production_alert_noise_fix._is_primary_service() is True
        assert log_service.is_primary_process() is True

        await lease.release()
        assert log_rectangle_v25._is_primary_process() is False
        assert passive_ai_single_reply_final._is_primary_service() is False
        assert production_alert_noise_fix._is_primary_service() is False
        assert log_service.is_primary_process() is False

    asyncio.run(scenario())


def test_forced_promotion_removes_stale_sqlite_wal_and_shm(tmp_path):
    snapshot_path = tmp_path / "snapshot.db"
    target_path = tmp_path / "standby.db"

    for path, marker in ((snapshot_path, "promoted"), (target_path, "stale")):
        conn = sqlite3.connect(path)
        try:
            for index in range(5):
                conn.execute(f"CREATE TABLE t{index} (value TEXT)")
            conn.execute("INSERT INTO t0 (value) VALUES (?)", (marker,))
            conn.commit()
        finally:
            conn.close()

    raw = snapshot_path.read_bytes()
    compressed = gzip.compress(raw)
    replica = DurableDatabaseReplica(str(target_path))
    replica.pool = FakeSnapshotPool({
        "id": 42,
        "checksum": hashlib.sha256(compressed).hexdigest(),
        "compressed_data": compressed,
        "sqlite_size": len(raw),
        "created_at": int(time.time()),
    })
    wal = tmp_path / "standby.db-wal"
    shm = tmp_path / "standby.db-shm"
    wal.write_bytes(b"stale wal")
    shm.write_bytes(b"stale shm")

    result = asyncio.run(replica.restore_latest_if_needed(force=True))
    assert result["restored"] is True
    assert not wal.exists()
    assert not shm.exists()
    conn = sqlite3.connect(target_path)
    try:
        assert conn.execute("SELECT value FROM t0").fetchone()[0] == "promoted"
    finally:
        conn.close()
