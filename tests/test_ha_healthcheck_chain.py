"""Milestone 4 (Observabilité) : railway_ha_boot.py::_install_ha_healthcheck
remplaçait purement dashboard.handle_health (web/health_runtime_v45.py::
enhanced_health, le diagnostic riche : DB, extensions, migrations, politique
de commandes) par un payload HA minimal, sans jamais l'appeler — motif
"remplacement dur au lieu de chaînage" déjà trouvé et corrigé ailleurs cette
session (§3/§9). Dès que le failover HA est actif (le cas réel sur Railway),
tout ce diagnostic devenait invisible.

Corrigé en chaînant : le handler précédent est appelé et son payload fusionné
avec les champs HA (failover), plutôt que remplacé.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import railway_ha_boot as ha_boot
from web import dashboard as dashboard_web


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.body = json.dumps(payload).encode()
        self.status = status


class _FakeCoordinatorHealth(dict):
    pass


def _fake_coordinator(*, enabled: bool, state: str, leader: bool = False):
    health = {
        "enabled": enabled, "state": state, "role": "leader" if leader else "standby",
        "leader": leader, "lock_key": "x" if enabled else None, "owner": None,
        "current_owner": None, "ttl_seconds": 30 if enabled else None,
        "renew_seconds": 10 if enabled else None, "leader_for_seconds": None, "error": None,
    }
    return SimpleNamespace(enabled=enabled, health=lambda: health)


def _fake_bot(*, ready: bool, latency: float = 0.05):
    return SimpleNamespace(
        is_ready=lambda: ready,
        is_closed=lambda: False,
        latency=latency,
    )


def _request(bot):
    return SimpleNamespace(app={"bot": bot})


def _install_over(monkeypatch, previous_payload: dict, coordinator):
    async def previous_handler(request):
        return _FakeResponse(previous_payload)

    dashboard_web.handle_health = previous_handler
    monkeypatch.setattr(ha_boot, "coordinator", coordinator)
    ha_boot._install_ha_healthcheck()
    return dashboard_web.handle_health


def test_chains_to_previous_handler_instead_of_replacing_it(monkeypatch):
    coordinator = _fake_coordinator(enabled=False, state="disabled")
    handler = _install_over(
        monkeypatch, {"ok": True, "migration_version": 3, "database_ok": True}, coordinator
    )
    bot = _fake_bot(ready=True)

    async def run():
        response = await handler(_request(bot))
        return json.loads(response.body)

    payload = asyncio.run(run())
    # Les champs du diagnostic riche doivent survivre à la fusion, pas disparaître.
    assert payload["migration_version"] == 3
    assert payload["database_ok"] is True
    assert "failover" in payload


def test_ha_disabled_defers_ok_to_the_rich_diagnostic(monkeypatch):
    coordinator = _fake_coordinator(enabled=False, state="disabled")
    handler = _install_over(monkeypatch, {"ok": False, "database_ok": False}, coordinator)
    bot = _fake_bot(ready=True)

    async def run():
        response = await handler(_request(bot))
        return json.loads(response.body), response.status

    payload, status = asyncio.run(run())
    assert payload["ok"] is False
    assert status == 503


def test_ready_leader_now_also_requires_the_rich_diagnostic_to_be_healthy(monkeypatch):
    """Avant ce correctif : un leader connecté à Discord était rapporté sain
    même avec une base de données cassée, puisque le diagnostic riche n'était
    jamais consulté. C'est exactement le bug corrigé ici."""
    coordinator = _fake_coordinator(enabled=True, state="leader", leader=True)
    handler = _install_over(
        monkeypatch, {"ok": False, "database_ok": False, "status": "database_unavailable"}, coordinator
    )
    bot = _fake_bot(ready=True)

    async def run():
        response = await handler(_request(bot))
        return json.loads(response.body), response.status

    payload, status = asyncio.run(run())
    assert payload["ok"] is False
    assert status == 503
    assert payload["database_ok"] is False


def test_ready_leader_healthy_when_rich_diagnostic_also_healthy(monkeypatch):
    coordinator = _fake_coordinator(enabled=True, state="leader", leader=True)
    handler = _install_over(monkeypatch, {"ok": True, "database_ok": True}, coordinator)
    bot = _fake_bot(ready=True)

    async def run():
        response = await handler(_request(bot))
        return json.loads(response.body), response.status

    payload, status = asyncio.run(run())
    assert payload["ok"] is True
    assert status == 200


def test_passive_standby_keeps_exact_same_leniency_as_before(monkeypatch):
    """Cas standby légitimement déconnecté (ready=False) : NE DOIT JAMAIS être
    gêné par le diagnostic riche, même si celui-ci dit ok=False (il le dira
    presque toujours, puisque discord_ready=False y contribue) — sinon on
    réintroduit exactement le problème que l'ancien code évitait déjà."""
    for state in ("starting", "standby", "blocked", "leader"):
        coordinator = _fake_coordinator(enabled=True, state=state, leader=(state == "leader"))
        handler = _install_over(
            monkeypatch, {"ok": False, "status": "discord_not_ready"}, coordinator
        )
        bot = _fake_bot(ready=False)

        async def run():
            response = await handler(_request(bot))
            return json.loads(response.body), response.status

        payload, status = asyncio.run(run())
        assert payload["ok"] is True, f"état {state} devrait rester sain"
        assert status == 200


def test_not_ready_and_ha_state_not_in_tolerated_set_is_unhealthy(monkeypatch):
    coordinator = _fake_coordinator(enabled=True, state="fenced")
    handler = _install_over(monkeypatch, {"ok": False}, coordinator)
    bot = _fake_bot(ready=False)

    async def run():
        response = await handler(_request(bot))
        return json.loads(response.body), response.status

    payload, status = asyncio.run(run())
    assert payload["ok"] is False
    assert status == 503


def test_idempotent_install_does_not_wrap_twice(monkeypatch):
    coordinator = _fake_coordinator(enabled=True, state="leader", leader=True)
    handler = _install_over(monkeypatch, {"ok": True}, coordinator)
    ha_boot._install_ha_healthcheck()
    assert dashboard_web.handle_health is handler


def test_falls_back_gracefully_if_previous_handler_raises(monkeypatch):
    async def broken_previous(request):
        raise RuntimeError("boom")

    dashboard_web.handle_health = broken_previous
    coordinator = _fake_coordinator(enabled=True, state="leader", leader=True)
    monkeypatch.setattr(ha_boot, "coordinator", coordinator)
    ha_boot._install_ha_healthcheck()
    bot = _fake_bot(ready=True)

    async def run():
        response = await dashboard_web.handle_health(_request(bot))
        return json.loads(response.body), response.status

    payload, status = asyncio.run(run())
    # Repli minimal : ne plante jamais, retombe sur le comportement HA seul.
    assert status == 200
    assert payload["ok"] is True
