"""04/11/2026 : un rôle d'arrivée supprimé ne relance plus le rattrapage en boucle.

Mesuré en production : 268 « Rôles d'arrivée écartés … Ce rôle n'existe plus »
en deux minutes pour les deux mêmes membres. Le rôle supprimé était compté comme
un échec ; le rattrapage des arrivées relançait alors les membres à chaque tour.
"""
from __future__ import annotations

import asyncio
import logging
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from utils import welcome_autoroles as wa  # noqa: E402


class _Db:
    def __init__(self, autorole):
        self.autorole = autorole

    async def get_guild_config(self, guild_id):
        return {"autorole": self.autorole}

    async def execute(self, *a, **k):
        return None

    async def fetchall(self, *a, **k):
        return []


def _membre(guild_id=1):
    guild = SimpleNamespace(id=guild_id, get_role=lambda _rid: None, me=None)
    return SimpleNamespace(bot=False, id=7, guild=guild, roles=[])


def test_un_role_supprime_est_definitif_et_signale_une_seule_fois(caplog):
    wa._DEJA_SIGNALES.clear()
    bot = SimpleNamespace(db=_Db(424242))
    with caplog.at_level(logging.WARNING, logger="bot.welcome-autoroles"):
        for _ in range(5):
            donnes, definitifs, temporaires = asyncio.run(wa.apply_detail(bot, _membre()))
    assert donnes == [] and temporaires == []
    assert definitifs == ["424242: Ce rôle n'existe plus."]
    assert sum("Rôles d'arrivée écartés" in r.message for r in caplog.records) == 1
    # L'API historique garde son contrat.
    assert asyncio.run(wa.apply(bot, _membre()))[1] == ["424242: Ce rôle n'existe plus."]


def test_un_refus_temporaire_de_discord_reste_a_reessayer():
    wa._DEJA_SIGNALES.clear()

    class Role:
        id = 5
        mention = "<@&5>"

    role = Role()
    guild = SimpleNamespace(id=2, get_role=lambda _rid: role)
    membre = SimpleNamespace(bot=False, id=8, guild=guild, roles=[])

    async def add_roles(*_a, **_k):
        raise discord.HTTPException(SimpleNamespace(status=503, reason="indisponible"), "x")

    membre.add_roles = add_roles
    original = wa.role_problem
    wa.role_problem = lambda _g, _r: None
    try:
        _d, definitifs, temporaires = asyncio.run(wa.apply_detail(SimpleNamespace(db=_Db(5)), membre))
    finally:
        wa.role_problem = original
    assert definitifs == [] and temporaires == ["5: Discord a refusé (503)"]


def test_l_arrivee_ne_compte_que_les_echecs_temporaires():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "cogs/setup_v2_completion.py").read_text(encoding="utf-8")
    assert "await welcome_autoroles.apply_detail(bot, member)" in source
    assert "roles_ok = not temporaires" in source
