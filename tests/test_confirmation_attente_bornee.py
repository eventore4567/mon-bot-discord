"""05/11/2026 : une confirmation jamais branchée ne bloque plus la commande.

Un +server-restore est resté suspendu 6 h 49 sur ConfirmView.wait() : le délai de
la vue n'a jamais déclenché (bot retiré du serveur juste après l'envoi).
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import helpers  # noqa: E402


def test_une_confirmation_orpheline_finit_par_expirer(monkeypatch):
    monkeypatch.setattr(helpers, "MARGE_ATTENTE_CONFIRMATION", 0.05)

    async def scenario():
        vue = helpers.ConfirmView(author_id=1, timeout=0.05)
        # Jamais envoyée : aucun minuteur discord.py ne tourne.
        expire = await asyncio.wait_for(vue.wait(), timeout=2)
        return vue, expire

    vue, expire = asyncio.run(scenario())
    assert expire is True
    assert vue.value is None  # rien n'est confirmé
    assert vue.is_finished()
