"""05/11/2026 : un log mis en attente (regroupement V17) garde son identité.

Capture : « Le salon Un salon a été supprimé. » — sans nom ni auteur. Le tampon
de regroupement rejouait l'événement sans les arguments d'identité.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from cogs import v17_tickets_logs as v17  # noqa: E402


def test_un_evenement_rejoue_garde_nom_et_auteur(monkeypatch):
    monkeypatch.setattr(v17, "LOG_BATCH_DELAY", 0)
    recus = []

    async def original(bot, guild, log_type, embed, file=None, **identity):
        recus.append(identity)
        return True

    guild = SimpleNamespace(id=1)
    bot = SimpleNamespace()
    cle = (1, "channel_delete", "channels")
    v17.state(bot).setdefault("v17_log_buffers", {})[cle] = [
        (guild, discord.Embed(title="Salon supprimé"), None,
         {"identity_name": "logs-salons", "identity_id": 42}),
    ]
    asyncio.run(v17._flush_group(bot, original, cle))
    assert recus == [{"identity_name": "logs-salons", "identity_id": 42}]
