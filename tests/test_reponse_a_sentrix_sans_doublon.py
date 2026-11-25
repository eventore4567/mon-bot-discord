"""25/11/2026 : « ok » envoyé après chaque sanction lancée par l'IA.

Sur un serveur, une réponse à SentriX était traitée deux fois : par
Ai.on_message (qui exécute l'action) puis par bot_experience_v5, qui relançait
l'analyse et, faute de résultat, demandait au modèle une réponse libre.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import bot_experience_v5 as v5  # noqa: E402


def test_une_reponse_a_sentrix_sur_un_serveur_n_est_pas_traitee_deux_fois(monkeypatch):
    ecouteurs = []
    ai = SimpleNamespace(_invoke_natural_command=AsyncMock(return_value=False),
                         send_sentrix_reply=AsyncMock())
    moi = SimpleNamespace(id=1)
    bot = SimpleNamespace(
        user=moi, get_cog=lambda _n: ai,
        add_listener=lambda fn, _evt: ecouteurs.append(fn),
    )
    monkeypatch.setattr(v5, "_is_blacklisted", AsyncMock(return_value=False))
    monkeypatch.setattr(v5, "_prefix_for", lambda _b, _m: "+")
    monkeypatch.setattr(v5, "_safe_reply_target", AsyncMock(return_value=SimpleNamespace(author=moi)))
    v5._install_reply_and_dm_conversations(bot)
    continuation = ecouteurs[0]

    message = SimpleNamespace(
        author=SimpleNamespace(id=5, bot=False), content="ban xDefender",
        guild=SimpleNamespace(id=10), mentions=[], reference=SimpleNamespace(message_id=99),
        channel=SimpleNamespace(),
    )
    asyncio.run(continuation(message))
    ai._invoke_natural_command.assert_not_awaited()
    ai.send_sentrix_reply.assert_not_awaited()
