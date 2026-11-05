"""05/11/2026 : le MP de sanction est une carte colorée, plus du texte brut."""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from services import moderation as svc  # noqa: E402


def _textes(vue):
    out = []

    def walk(item):
        if isinstance(getattr(item, "content", None), str):
            out.append(item.content)
        for enfant in getattr(item, "children", ()) or ():
            walk(enfant)

    walk(vue)
    return "\n".join(out)


def test_un_unmute_est_une_carte_verte():
    vue = svc._carte_mp("Votre mute sur Mon Serveur a été retiré.\nRaison : calme revenu")
    carte = vue.children[0]
    assert carte.accent_colour.value == 0x57F287
    texte = _textes(vue)
    assert "### ✅ Votre mute sur Mon Serveur a été retiré." in texte
    assert "Raison : calme revenu" in texte


def test_une_sanction_est_une_carte_rouge():
    vue = svc._carte_mp("Vous avez été rendu muet sur Mon Serveur pendant 10 minutes.\nRaison : spam")
    assert vue.children[0].accent_colour.value == 0xED4245
    assert "🛑" in _textes(vue)


def test_si_discord_refuse_la_carte_le_texte_part_quand_meme():
    target = type("T", (), {})()
    appels = []

    async def send(*args, **kwargs):
        appels.append(kwargs.get("view") is not None)
        if kwargs.get("view") is not None:
            raise discord.HTTPException(type("R", (), {"status": 400, "reason": "x"})(), "bad")

    target.send = send
    assert asyncio.run(svc._send_dm_best_effort(target, "Votre mute a été retiré.")) is True
    assert appels == [True, False]


def test_un_mp_ferme_n_est_pas_retente():
    target = type("T", (), {})()
    target.send = AsyncMock(side_effect=discord.Forbidden(type("R", (), {"status": 403, "reason": "x"})(), "fermé"))
    assert asyncio.run(svc._send_dm_best_effort(target, "Sanction")) is False
    assert target.send.await_count == 1
