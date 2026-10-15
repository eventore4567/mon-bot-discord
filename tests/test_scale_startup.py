"""Démarrage à grande échelle : ce qui se faisait « pour chaque serveur » à chaque on_ready.

Mesuré (tools/scale_ready_probe.py) : 3 appels Discord et ~20 opérations base par
serveur à chaque démarrage et reconnexion. Après correction : au redémarrage, plus
que le préchargement étalé des invitations, et 0,02 opération base par serveur.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from cogs import invites as invites_module  # noqa: E402
from utils import once_per_guild  # noqa: E402


def _invite(code: str, uses: int) -> Mock:
    invite = Mock(spec=discord.Invite)
    invite.code = code
    invite.uses = uses
    invite.inviter = Mock(id=42)
    return invite


def _guild(gid: int, members: int, *, manage: bool = True, invites=None) -> Mock:
    guild = Mock()
    guild.id = gid
    guild.member_count = members
    guild.features = []
    guild.me = SimpleNamespace(guild_permissions=SimpleNamespace(manage_guild=manage))
    guild.invites = AsyncMock(return_value=list(invites or []))
    return guild


@pytest.mark.asyncio
async def test_sans_reference_l_arrivee_n_est_pas_attribuee_au_hasard():
    """Avant : cache vide -> la première invitation déjà utilisée était désignée."""
    cog = invites_module.Invites(SimpleNamespace(guilds=[]))
    guild = _guild(1, 50, invites=[_invite("ancienne", 30), _invite("autre", 2)])
    assert await cog.find_used_invite(guild) is None
    assert cog.invite_cache[1] == {"ancienne": 30, "autre": 2}

    guild.invites.return_value = [_invite("ancienne", 30), _invite("autre", 3)]
    used = await cog.find_used_invite(guild)
    assert used is not None and used.code == "autre"


@pytest.mark.asyncio
async def test_prechargement_etale_gros_serveurs_d_abord_sans_appel_inutile(monkeypatch):
    monkeypatch.setattr(invites_module, "INVITE_PREFETCH_INTERVAL", 0)
    petit, gros, sans_droit = _guild(1, 10), _guild(2, 5000), _guild(3, 9000, manage=False)
    order = []
    for g in (petit, gros, sans_droit):
        g.invites.side_effect = lambda g=g: order.append(g.id) or []
    bot = SimpleNamespace(guilds=[petit, gros, sans_droit])
    cog = invites_module.Invites(bot)

    await cog.on_ready()
    await cog._prefetch_task
    assert order == [2, 1], "le plus gros d'abord, et aucun appel sans « Gérer le serveur »"

    # Une reconnexion ne refait pas les serveurs déjà en cache.
    await cog.on_ready()
    await cog._prefetch_task
    assert order == [2, 1]


class _Db:
    def __init__(self):
        self.rows: set[tuple[str, int]] = set()
        self.calls = 0

    async def execute(self, query, params=()):
        self.calls += 1
        if query.startswith("INSERT"):
            self.rows.add((params[0], params[1]))
        elif query.startswith("DELETE"):
            self.rows.discard((params[0], params[1]))

    async def fetchall(self, query, params=()):
        self.calls += 1
        return [{"guild_id": g} for task, g in self.rows if task == params[0]]


@pytest.mark.asyncio
async def test_un_travail_par_serveur_n_est_fait_qu_une_fois_et_se_lit_en_une_requete():
    bot = SimpleNamespace(db=_Db())
    assert await once_per_guild.restants(bot, "t", [1, 2, 3]) == [1, 2, 3]
    await once_per_guild.marquer(bot, "t", 2)
    before = bot.db.calls
    assert await once_per_guild.restants(bot, "t", range(1, 10_001)) == [g for g in range(1, 10_001) if g != 2]
    assert bot.db.calls - before == 1, "une requête, quel que soit le nombre de serveurs"
    assert await once_per_guild.restants(bot, "autre", [2]) == [2], "chaque travail a son propre registre"
    await once_per_guild.oublier(bot, "t", 2)
    assert await once_per_guild.restants(bot, "t", [2]) == [2]
