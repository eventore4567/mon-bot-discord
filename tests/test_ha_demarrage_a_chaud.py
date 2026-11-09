"""09/11/2026 : déploiement sans pause. La nouvelle instance charge tout AVANT de
prendre le bail ; /health reste en 503 pendant ce chargement ; les boucles de fond
attendent le bail ; au bail, il ne reste que la connexion à Discord."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord.ext.tasks  # noqa: E402

import railway_ha_boot as ha  # noqa: E402


@pytest.fixture(autouse=True)
def _etat_propre(monkeypatch):
    monkeypatch.setattr(ha, "_DEMARRAGE_A_CHAUD", True)
    monkeypatch.setattr(ha, "_chaud", {"en_cours": False, "pret": False, "erreur": None})
    monkeypatch.setattr(ha, "_boucles_differees", [])
    monkeypatch.setattr(ha.coordinator, "enabled", True, raising=False)
    monkeypatch.setattr(ha.coordinator, "start_watchdog", lambda bot: None, raising=False)
    monkeypatch.setattr(ha, "_prepare_leader_storage", AsyncMock())
    monkeypatch.setattr(ha, "_installer_arret_gracieux", lambda bot: True)
    monkeypatch.setattr(ha, "_periodic_snapshot_loop", AsyncMock())
    yield
    discord.ext.tasks.Loop.start = ha._original_loop_start


@pytest.mark.asyncio
async def test_tout_est_charge_avant_le_bail_puis_seule_la_connexion_reste(monkeypatch):
    ordre: list[str] = []

    @discord.ext.tasks.loop(seconds=60)
    async def boucle():
        ordre.append("boucle tourne")

    async def login(token):
        ordre.append("login + modules")
        boucle.start()                         # un module démarre sa boucle pendant le chargement
        assert not boucle.is_running()         # … différée : l'instance n'est pas leader
        assert ha._chaud["en_cours"] and not ha._chaud["pret"]

    async def attendre_bail():
        ordre.append("bail")
        assert ha._chaud["pret"]
        return SimpleNamespace(acquired_immediately=True, waited_seconds=0.0)

    async def connect(reconnect=True):
        ordre.append("connexion")
        assert boucle.is_running()             # la boucle démarre au bail
        boucle.cancel()

    monkeypatch.setattr(ha.coordinator, "wait_for_leadership", attendre_bail, raising=False)
    bot = SimpleNamespace(login=login, connect=connect)
    original = AsyncMock()
    monkeypatch.setattr(ha, "_original_bot_start", original)

    await ha._ha_bot_start(bot, "token")
    assert ordre[:3] == ["login + modules", "bail", "connexion"]
    original.assert_not_awaited()             # plus de login après le bail
    assert discord.ext.tasks.Loop.start is ha._original_loop_start


@pytest.mark.asyncio
async def test_health_en_503_pendant_le_chargement(monkeypatch):
    async def sante_d_origine(request):
        return SimpleNamespace(body=b'{"ok": true}')

    monkeypatch.setattr(ha.dashboard_web, "handle_health", sante_d_origine)
    ha._install_ha_healthcheck()
    sante = ha.dashboard_web.handle_health
    monkeypatch.setattr(ha.coordinator, "health", lambda: {
        "enabled": True, "state": "starting", "role": "primary", "leader": False,
        "ttl_seconds": 30, "leader_for_seconds": 0, "error": None,
    }, raising=False)
    bot = SimpleNamespace(is_ready=lambda: False, is_closed=lambda: False, latency=0.0)
    requete = SimpleNamespace(app={"bot": bot})
    ha._chaud.update(en_cours=True, pret=False)
    assert (await sante(requete)).status == 503
    ha._chaud.update(pret=True)
    assert (await sante(requete)).status == 200


def test_desactivable():
    import inspect

    source = inspect.getsource(ha)
    assert 'os.getenv("SENTRIX_HA_WARM", "1")' in source


def test_health_en_503_des_le_demarrage_du_processus():
    import importlib

    module = importlib.reload(ha)
    try:
        assert module._chaud["en_cours"] is module._DEMARRAGE_A_CHAUD
        assert module._chaud["pret"] is False
    finally:
        importlib.reload(module)
