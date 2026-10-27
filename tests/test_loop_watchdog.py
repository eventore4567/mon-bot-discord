"""utils/loop_watchdog : un blocage de la boucle est signalé AVEC le code fautif."""
from __future__ import annotations

import asyncio
import logging
import os
import time

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import loop_watchdog  # noqa: E402


def _calcul_bloquant():
    time.sleep(1.6)  # du code synchrone dans une coroutine : la boucle est figée


def test_un_blocage_est_signale_avec_la_fonction_fautive(caplog):
    async def scenario():
        loop_watchdog.demarrer(asyncio.get_running_loop())
        await asyncio.sleep(0.6)
        _calcul_bloquant()
        await asyncio.sleep(0.3)
        loop_watchdog.arreter()

    with caplog.at_level(logging.WARNING, logger="bot.loop-watchdog"):
        asyncio.run(scenario())
    messages = [r.getMessage() for r in caplog.records if r.name == "bot.loop-watchdog"]
    assert any("Boucle bloquée" in m and "_calcul_bloquant" in m for m in messages), messages


def test_une_boucle_fluide_ne_signale_rien(caplog):
    async def scenario():
        loop_watchdog.demarrer(asyncio.get_running_loop())
        for _ in range(8):
            await asyncio.sleep(0.2)
        loop_watchdog.arreter()

    with caplog.at_level(logging.WARNING, logger="bot.loop-watchdog"):
        asyncio.run(scenario())
    assert not [r for r in caplog.records if r.name == "bot.loop-watchdog" and r.levelno >= logging.WARNING]


def test_ancien_thread_ignore_une_nouvelle_generation(caplog):
    """Une vieille surveillance n'a pas le droit d'alerter au cycle suivant."""
    import threading

    saved = dict(loop_watchdog._etat)
    try:
        previous_generation = int(saved["generation"])
        loop_watchdog._etat.update({
            "generation": previous_generation + 1,
            "actif": True,
            "dernier": time.monotonic() - 10,
        })
        with caplog.at_level(logging.WARNING, logger="bot.loop-watchdog"):
            loop_watchdog._surveiller(threading.get_ident(), previous_generation)
        assert not [record for record in caplog.records if record.name == "bot.loop-watchdog"]
    finally:
        loop_watchdog._etat.update(saved)


def test_ancien_battement_ne_modifie_pas_l_etat_d_un_nouveau_cycle():
    saved = dict(loop_watchdog._etat)
    try:
        previous_generation = int(saved["generation"])
        loop_watchdog._etat.update({
            "generation": previous_generation + 1,
            "actif": True,
            "dernier": 123.0,
        })
        asyncio.run(loop_watchdog._battre(previous_generation))
        assert loop_watchdog._etat["dernier"] == 123.0
    finally:
        loop_watchdog._etat.update(saved)
