"""L'audit de démarrage ne compte pas l'attente du bail HA comme un retard Discord."""
import asyncio
import logging
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from web import health_runtime_v45 as module


def _lancer(monkeypatch, caplog, *, pret_au_second_essai):
    appels = []

    async def attente(coro, timeout):
        appels.append(timeout)
        coro.close()
        if len(appels) == 1 or not pret_au_second_essai:
            raise asyncio.TimeoutError
        return None

    async def instantane(_bot, _dashboard):
        return {"ok": True, "extensions_loaded": 73, "extensions_expected": 73, "database_latency_ms": 1.0}

    async def pret():
        return None

    monkeypatch.setattr(module.asyncio, "wait_for", attente)
    monkeypatch.setattr(module, "_ha_runtime_state", lambda _bot: (True, True, "primary", "leader"))
    monkeypatch.setattr(module, "_snapshot", instantane)
    bot = SimpleNamespace(wait_until_ready=pret)
    with caplog.at_level(logging.INFO, logger=module.logger.name):
        asyncio.run(module._boot_audit(bot, None))
    return appels


def test_leader_pret_peu_apres_le_bail_sans_erreur(monkeypatch, caplog):
    appels = _lancer(monkeypatch, caplog, pret_au_second_essai=True)
    assert appels == [90, 90]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert "Audit démarrage V45 OK" in caplog.text


def test_leader_vraiment_bloque_reste_en_erreur(monkeypatch, caplog):
    _lancer(monkeypatch, caplog, pret_au_second_essai=False)
    assert any(r.levelno == logging.ERROR and "après la prise du bail" in r.getMessage() for r in caplog.records)
