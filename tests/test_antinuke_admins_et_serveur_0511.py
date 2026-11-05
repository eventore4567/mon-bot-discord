"""05/11/2026 : l'anti-nuke surveille les admins et l'identité du serveur.

Test réel : un compte admin secondaire a supprimé tous les salons et renommé le
serveur sans aucune réaction.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.automod import AutoMod  # noqa: E402


def _cog(actor_id=77, antinuke=1):
    cog = AutoMod.__new__(AutoMod)
    cog.bot = SimpleNamespace(user=SimpleNamespace(id=2))
    cog.get_automod_cached = AsyncMock(return_value={"antinuke": antinuke})
    cog.get_audit_actor = AsyncMock(return_value=SimpleNamespace(id=actor_id))
    cog.is_antinuke_exempt = AsyncMock(return_value=False)
    compteur = {"n": 0}

    async def record(guild, actor):
        compteur["n"] += 1
        return compteur["n"] >= 3

    cog.record_nuke_action = record
    cog.punish_nuker = AsyncMock()
    return cog


def _serveur(nom):
    return SimpleNamespace(id=1, name=nom, icon=None, banner=None, splash=None, description=None,
                           edit=AsyncMock())


def test_trois_renommages_rapides_sanctionnent_et_remettent_le_nom_d_origine():
    cog = _cog()

    async def scenario():
        noms = ["Mon Serveur", "NUKED 1", "NUKED 2", "NUKED 3"]
        dernier = None
        for avant, apres in zip(noms, noms[1:]):
            dernier = _serveur(apres)
            await cog._garde_identite_serveur(_serveur(avant), dernier)
        return dernier

    dernier = asyncio.run(scenario())
    cog.punish_nuker.assert_awaited_once()
    dernier.edit.assert_awaited_once()
    assert dernier.edit.await_args.kwargs["name"] == "Mon Serveur"


def test_un_seul_renommage_ne_sanctionne_personne():
    cog = _cog()
    asyncio.run(cog._garde_identite_serveur(_serveur("A"), _serveur("B")))
    cog.punish_nuker.assert_not_awaited()


def test_anti_nuke_eteint_ne_fait_rien():
    cog = _cog(antinuke=0)
    for _ in range(4):
        asyncio.run(cog._garde_identite_serveur(_serveur("A"), _serveur("B")))
    cog.punish_nuker.assert_not_awaited()


def test_huit_pings_de_la_meme_personne_dans_un_message_sont_detectes():
    import datetime as dt

    cog = AutoMod.__new__(AutoMod)
    cog.bot = SimpleNamespace(user=SimpleNamespace(id=2))
    cible = SimpleNamespace(id=500, bot=False)
    message = SimpleNamespace(
        author=SimpleNamespace(id=9),
        guild=SimpleNamespace(id=1),
        mentions=[cible],
        role_mentions=[],
        reference=None,
        content=" ".join(["<@500>"] * 8),
        created_at=dt.datetime.now(dt.timezone.utc),
    )
    assert cog._pings_repetes(message) == "Mentions répétées (ping spam)."
