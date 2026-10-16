"""Résumé d'usage des commandes (utils/command_usage.py) : comptes seuls, aucune donnée de membre."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import aiosqlite  # noqa: E402

from utils import command_usage  # noqa: E402

MAINTENANT = 1_800_000_000
JOUR = 86400


class _Db:
    def __init__(self, conn):
        self.conn = conn

    async def fetchall(self, sql, params=()):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchall()

    async def fetchone(self, sql, params=()):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()


async def _resume(lignes, catalogue):
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("CREATE TABLE command_logs (id INTEGER PRIMARY KEY, guild_id INTEGER, "
                           "user_id INTEGER, command_name TEXT, timestamp INTEGER)")
        await conn.executemany("INSERT INTO command_logs (guild_id,user_id,command_name,timestamp) "
                               "VALUES (?,?,?,?)", lignes)
        return await command_usage.resume(_Db(conn), catalogue, maintenant=MAINTENANT)


def test_compte_par_commande_et_serveurs_sur_la_periode():
    lignes = [
        (1, 10, "ping", MAINTENANT - JOUR), (2, 11, "ping", MAINTENANT - 2 * JOUR),
        (1, 10, "economy balance", MAINTENANT - JOUR),
        (1, 10, "ban", MAINTENANT - 60 * JOUR),  # hors période
    ]
    r = asyncio.run(_resume(lignes, ["ping", "ban", "economy", "economy balance", "help"]))
    assert r["total"] == 3 and r["serveurs"] == 2
    assert r["top"][0] == ("ping", (2, 2))
    # « economy » (groupe) est utilisé par sa sous-commande ; ban est hors période.
    assert r["jamais"] == ["ban", "help"]
    assert r["depuis"] == MAINTENANT - 60 * JOUR


def test_les_lignes_de_journal_ne_contiennent_aucun_identifiant_de_membre():
    lignes = [(100000000000000001, 424242424242424242, "ping", MAINTENANT - JOUR)]
    r = asyncio.run(_resume(lignes, ["ping", "help"]))
    texte = "\n".join(command_usage.lignes_de_journal(r))
    assert "424242424242424242" not in texte and "100000000000000001" not in texte
    assert "1/2 commandes utilisées" in texte and "ping=1 (1 srv)" in texte
    assert "USAGE JAMAIS 30 j (1) : help" in texte


def test_longue_liste_decoupee_en_lignes_lisibles():
    r = asyncio.run(_resume([], [f"commande-{i:03d}" for i in range(300)]))
    lignes = command_usage.lignes_de_journal(r)
    assert all(len(l) <= command_usage.LIGNE_MAX + 40 for l in lignes)
    jamais = [l for l in lignes if l.startswith("USAGE JAMAIS")]
    assert len(jamais) > 1 and "journal depuis aucune donnée" in lignes[0]


def test_depuis_le_debut_couvre_tout_le_journal():
    lignes = [(1, 10, "ban", MAINTENANT - 60 * JOUR), (1, 10, "ping", MAINTENANT - JOUR)]

    async def run():
        async with aiosqlite.connect(":memory:") as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("CREATE TABLE command_logs (id INTEGER PRIMARY KEY, guild_id INTEGER, "
                               "user_id INTEGER, command_name TEXT, timestamp INTEGER)")
            await conn.executemany("INSERT INTO command_logs (guild_id,user_id,command_name,timestamp) "
                                   "VALUES (?,?,?,?)", lignes)
            return await command_usage.resume(_Db(conn), ["ban", "ping", "help"], jours=None,
                                              maintenant=MAINTENANT)

    r = asyncio.run(run())
    assert r["total"] == 2 and r["jamais"] == ["help"]
    assert command_usage.lignes_de_journal(r)[0].startswith("USAGE COMMANDES DEPUIS LE DÉBUT")
