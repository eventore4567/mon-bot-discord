"""09/11/2026 : mesure du temps passé par chaque écouteur on_message."""
import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from utils import mesure_ecouteurs as m  # noqa: E402


def test_le_temps_de_chaque_ecouteur_est_mesure_sans_changer_son_execution():
    m._totaux.clear()
    appels = []

    class Cog:
        async def on_message(self, message):
            await asyncio.sleep(0.01)
            appels.append(message)

    client = SimpleNamespace(on_error=None)
    asyncio.run(m._run_event_mesure(client, Cog().on_message, "on_message", "msg"))
    asyncio.run(m._run_event_mesure(client, Cog().on_message, "on_ready", "autre"))  # non mesuré
    assert appels == ["msg", "autre"]
    [(nom, total, nb, pire)] = m.rapport()
    assert nom.endswith("Cog.on_message") and nb == 1 and total >= 0.009 and pire >= 0.009


def test_installe_une_seule_fois(monkeypatch):
    original = discord.Client._run_event
    monkeypatch.setattr(discord.Client, "_run_event", m._original_run_event)
    boucle = asyncio.new_event_loop()
    try:
        bot = SimpleNamespace(loop=boucle)
        assert m.installer(bot) is True
        assert m.installer(bot) is False
    finally:
        for tache in asyncio.all_tasks(boucle):
            tache.cancel()
        boucle.close()
        discord.Client._run_event = original
