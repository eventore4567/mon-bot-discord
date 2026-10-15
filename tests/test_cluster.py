"""Plusieurs processus actifs (utils/cluster.py) — et un serveur absent n'est pas un serveur quitté.

Plusieurs tâches de fond marquaient des tickets « supprimés » ou levaient des
quarantaines dès que ``get_guild`` ne rendait rien — ou rendait un serveur
momentanément indisponible (panne Discord : aucun salon). Avec plusieurs
processus, les serveurs des AUTRES processus sont toujours « absents ».
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import cluster  # noqa: E402


def _guild_on_shard(shard: int, shard_count: int) -> int:
    return (shard + shard_count * 1000) << 22


def test_un_seul_cluster_tout_lui_appartient(monkeypatch):
    monkeypatch.delenv("SENTRIX_CLUSTER_COUNT", raising=False)
    bot = SimpleNamespace(shard_ids=None, shard_count=1)
    assert cluster.cluster_count() == 1 and cluster.is_primary_cluster()
    assert cluster.owns_guild(bot, 123456789012345678)


def test_les_shards_sont_repartis_sans_trou_ni_doublon(monkeypatch):
    monkeypatch.setenv("SENTRIX_CLUSTER_COUNT", "3")
    parts = [cluster.shard_ids_for_cluster(10, cluster=c) for c in range(3)]
    assert sorted(s for part in parts for s in part) == list(range(10))
    assert parts[0] == [0, 3, 6, 9]


def test_etat_serveur_ne_conclut_au_depart_que_si_c_est_sur():
    present = SimpleNamespace(unavailable=False)
    panne = SimpleNamespace(unavailable=True)
    guilds = {_guild_on_shard(0, 2): present, _guild_on_shard(0, 2) + 1: panne}
    bot = SimpleNamespace(shard_ids=[0], shard_count=2, get_guild=guilds.get, is_ready=lambda: True)

    assert cluster.etat_serveur(bot, _guild_on_shard(0, 2)) == (present, cluster.PRESENT)
    assert cluster.etat_serveur(bot, _guild_on_shard(0, 2) + 1) == (None, cluster.INDISPONIBLE)
    assert cluster.etat_serveur(bot, _guild_on_shard(1, 2)) == (None, cluster.AILLEURS)
    assert cluster.etat_serveur(bot, _guild_on_shard(0, 2) + 2) == (None, cluster.PARTI)
    pas_pret = SimpleNamespace(shard_ids=None, shard_count=1, get_guild=lambda _i: None, is_ready=lambda: False)
    assert cluster.etat_serveur(pas_pret, 42) == (None, cluster.INDISPONIBLE)


def test_une_quarantaine_n_est_pas_levee_pendant_une_panne_discord():
    from cogs import security_tools

    executed = []

    async def execute(sql, params=()):
        executed.append((sql, params))

    row = {"id": 7, "guild_id": 42, "user_id": 1, "expires_at": 0}
    db = SimpleNamespace(fetchall=AsyncMock(return_value=[row]), execute=execute)
    panne = SimpleNamespace(unavailable=True)
    bot = SimpleNamespace(db=db, shard_ids=None, shard_count=1, get_guild=lambda _i: panne, is_ready=lambda: True)
    cog = security_tools.Security.__new__(security_tools.Security)
    cog.bot = bot
    asyncio.run(security_tools.Security.check_quarantines.coro(cog))
    assert not any("active = 0" in sql for sql, _ in executed), "la quarantaine doit rester active"

    # Le bot a vraiment quitté le serveur : la ligne est soldée.
    bot.get_guild = lambda _i: None
    asyncio.run(security_tools.Security.check_quarantines.coro(cog))
    assert any("active = 0" in sql for sql, _ in executed)


@pytest.mark.asyncio
async def test_totaux_additionnent_les_autres_clusters(monkeypatch):
    monkeypatch.setenv("SENTRIX_CLUSTER_COUNT", "2")
    monkeypatch.setenv("SENTRIX_CLUSTER_ID", "0")
    db = SimpleNamespace(execute=AsyncMock(), fetchall=AsyncMock(return_value=[{"cluster_id": 1, "guilds": 40, "members": 900}]))
    bot = SimpleNamespace(db=db, guilds=[SimpleNamespace(member_count=10)] * 3)
    assert await cluster.totaux(bot) == {"guilds": 43, "members": 930, "clusters": 2}
