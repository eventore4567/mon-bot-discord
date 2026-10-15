"""Démarrage haute disponibilité sur base principale PostgreSQL.

En SQLite, le leader pousse un snapshot « de référence » et un secours qui prend
la main restaure le dernier snapshot. En PostgreSQL, la base est partagée : le
snapshot est désactivé (il enregistrerait un fichier figé), donc exiger le
snapshot de référence empêchait le leader de démarrer, et la « restauration »
fermait la connexion pour restaurer un fichier que le bot n'utilise plus.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("DISCORD_TOKEN", "x")

import railway_ha_boot as ha  # noqa: E402


def _durable():
    return SimpleNamespace(
        configured=True, pool=object(), connect=AsyncMock(return_value=True),
        snapshot=AsyncMock(return_value={"stored": True, "snapshot_id": 1}),
        restore_latest_if_needed=AsyncMock(return_value={"restored": True, "snapshot_id": 1}),
        force_restore=False,
    )


def _grant():
    return SimpleNamespace(acquired_immediately=False, waited_seconds=1.0)


@pytest.mark.asyncio
async def test_postgres_le_leader_demarre_sans_snapshot_ni_restauration(monkeypatch):
    monkeypatch.setattr(ha.coordinator, "enabled", True, raising=False)
    monkeypatch.setattr(ha.coordinator, "role", "standby", raising=False)
    durable = _durable()
    db = SimpleNamespace(backend="postgres", close=AsyncMock(), set_config_snapshot_callback=lambda *a, **k: None)
    await ha._prepare_leader_storage(SimpleNamespace(db=db), durable, _grant())
    durable.snapshot.assert_not_awaited()
    durable.restore_latest_if_needed.assert_not_awaited()
    db.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_sqlite_le_primaire_pousse_toujours_son_snapshot_de_reference(monkeypatch):
    monkeypatch.setattr(ha.coordinator, "enabled", True, raising=False)
    monkeypatch.setattr(ha.coordinator, "role", "primary", raising=False)
    monkeypatch.setattr(ha.coordinator, "reprise_de_soi", lambda: False, raising=False)
    # La garde « seul le leader écrit un snapshot » est testée ailleurs.
    monkeypatch.setattr(ha, "_guard_durable_snapshots", lambda durable: None)
    durable = _durable()
    grant = SimpleNamespace(acquired_immediately=True, waited_seconds=0.0)
    db = SimpleNamespace(backend="sqlite", set_config_snapshot_callback=lambda *a, **k: None)
    await ha._prepare_leader_storage(SimpleNamespace(db=db), durable, grant)
    assert durable.snapshot.await_count >= 1
