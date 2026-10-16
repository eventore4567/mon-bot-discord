"""« SentriX réfléchit… » seulement pour une commande « / » lente (sentrix_grouped_slash_fix).

Avant : defer immédiat avant TOUTE commande, même instantanée. Le parcours complet
sur le bot booté est tools/slash_defer_e2e.py ; ici, la règle seule, en millisecondes.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import sentrix_grouped_slash_fix as fix  # noqa: E402


class _Response:
    def __init__(self):
        self.calls = []

    def is_done(self):
        return bool(self.calls)

    async def defer(self, **kwargs):
        self.calls.append(("defer", kwargs))

    async def send_message(self, content=None, **kwargs):
        self.calls.append(("send", content, kwargs))


def _interaction():
    return SimpleNamespace(response=_Response(), extras={})


def test_commande_rapide_aucun_defer(monkeypatch):
    monkeypatch.setattr(fix, "SLOW_COMMAND_DEFER_SECONDS", 0.05)
    interaction = _interaction()

    async def run():
        timer = asyncio.create_task(fix._defer_if_slow(interaction))
        await interaction.response.send_message("pong")
        await asyncio.sleep(0.1)
        timer.cancel()

    asyncio.run(run())
    assert [c[0] for c in interaction.response.calls] == ["send"]


def test_commande_lente_defer_avant_la_limite(monkeypatch):
    monkeypatch.setattr(fix, "SLOW_COMMAND_DEFER_SECONDS", 0.05)
    interaction = _interaction()

    async def run():
        await fix._defer_if_slow(interaction)

    asyncio.run(run())
    assert interaction.response.calls == [("defer", {"thinking": True})]
    assert interaction.extras["sentrix_slow_defer"] is True
    assert fix.SLOW_COMMAND_DEFER_SECONDS < 3


def test_commande_silencieuse_confirmation_ephemere():
    interaction = _interaction()
    timer = SimpleNamespace(cancelled=False, cancel=lambda: setattr(timer, "cancelled", True))
    interaction.extras["sentrix_slow_timer"] = timer
    asyncio.run(fix._acknowledge_if_silent(interaction))
    assert timer.cancelled
    assert interaction.response.calls == [("send", "Commande exécutée.", {"ephemeral": True})]


def test_reponse_deja_faite_rien_de_plus():
    interaction = _interaction()
    interaction.response.calls.append(("send", "déjà", {}))
    asyncio.run(fix._acknowledge_if_silent(interaction))
    assert len(interaction.response.calls) == 1
