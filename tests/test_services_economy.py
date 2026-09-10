"""services/economy.py — sell/withdraw/deposit/gamble/rob sont chacun
enveloppés par un patch qui remplace la commande réellement exécutée en
production (cogs/integrity_hardening.py pour les quatre premiers,
cogs/sentrix_v22.py pour rob) — confirmé en traçant __code__.co_filename/
co_firstlineno sur un boot identique à la production (51 extensions), qui ne
ment jamais contrairement à __qualname__ (recopié par functools.wraps d'une
couche à l'autre). Voir docs/core-v2-audit-economy-atomicity.md.

Ces fonctions ont été déplacées telles quelles (aucun changement de
comportement) hors de ces deux cogs pour devenir testables directement,
contre une vraie base SQLite en mémoire plutôt que des mocks — le but même de
ce module est l'atomicité transactionnelle, qu'un mock de connexion ne peut
pas vérifier fidèlement."""
from __future__ import annotations

import asyncio
import os
import sqlite3
import unittest
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import aiosqlite

from services import economy


SCHEMA = """
CREATE TABLE economy (
    guild_id INTEGER, user_id INTEGER,
    cash INTEGER DEFAULT 0, bank INTEGER DEFAULT 0,
    last_rob INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE shop_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER, name TEXT, price INTEGER, role_id INTEGER
);
CREATE TABLE inventory (
    guild_id INTEGER, user_id INTEGER, item_name TEXT, quantity INTEGER DEFAULT 1,
    UNIQUE (guild_id, user_id, item_name)
);
CREATE TABLE economy_transactions (
    transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER, sender_id INTEGER, receiver_id INTEGER,
    transaction_type TEXT, amount INTEGER, created_at INTEGER, reason TEXT DEFAULT ''
);
"""


class _FakeDB:
    """Reproduit la surface utilisée par services/economy.py : ._conn (une vraie
    connexion aiosqlite) et ._economy_lock (le même verrou que production/db.py)."""

    def __init__(self, conn):
        self._conn = conn
        self._economy_lock = asyncio.Lock()


async def _make_db():
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    await conn.commit()
    return _FakeDB(conn)


async def _seed_economy(db, guild_id, user_id, *, cash=0, bank=0, last_rob=0):
    await db._conn.execute(
        "INSERT INTO economy (guild_id,user_id,cash,bank,last_rob) VALUES (?,?,?,?,?)",
        (guild_id, user_id, cash, bank, last_rob),
    )
    await db._conn.commit()


async def _cash_bank(db, guild_id, user_id):
    cur = await db._conn.execute(
        "SELECT cash,bank FROM economy WHERE guild_id=? AND user_id=?", (guild_id, user_id)
    )
    row = await cur.fetchone()
    await cur.close()
    return (row["cash"], row["bank"]) if row else (None, None)


class AtomicBankTransferTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = await _make_db()

    async def asyncTearDown(self):
        await self.db._conn.close()

    async def test_deposit_deplace_cash_vers_banque(self):
        await _seed_economy(self.db, 1, 2, cash=100, bank=0)
        status, amount = await economy.atomic_bank_transfer(self.db, 1, 2, "60", deposit=True)
        self.assertEqual(status, "ok")
        self.assertEqual(amount, 60)
        self.assertEqual(await _cash_bank(self.db, 1, 2), (40, 60))

    async def test_withdraw_deplace_banque_vers_cash(self):
        await _seed_economy(self.db, 1, 2, cash=10, bank=100)
        status, amount = await economy.atomic_bank_transfer(self.db, 1, 2, "all", deposit=False)
        self.assertEqual(status, "ok")
        self.assertEqual(amount, 100)
        self.assertEqual(await _cash_bank(self.db, 1, 2), (110, 0))

    async def test_montant_superieur_au_solde_est_invalide(self):
        await _seed_economy(self.db, 1, 2, cash=10, bank=0)
        status, amount = await economy.atomic_bank_transfer(self.db, 1, 2, "9999", deposit=True)
        self.assertEqual(status, "invalid")
        self.assertEqual(amount, 0)
        self.assertEqual(await _cash_bank(self.db, 1, 2), (10, 0))

    async def test_compte_absent_est_cree_a_zero_puis_rejete(self):
        status, amount = await economy.atomic_bank_transfer(self.db, 1, 999, "10", deposit=True)
        self.assertEqual(status, "invalid")
        self.assertEqual(amount, 0)

    async def test_depots_concurrents_all_ne_dupliquent_jamais_largent(self):
        """Avant le correctif d'origine : deux 'all' concurrents pouvaient tous les deux
        lire le même solde avant qu'aucun n'écrive, doublant l'argent transféré. Le verrou
        _economy_lock doit sérialiser les deux appels."""
        await _seed_economy(self.db, 1, 2, cash=100, bank=0)
        results = await asyncio.gather(
            economy.atomic_bank_transfer(self.db, 1, 2, "all", deposit=True),
            economy.atomic_bank_transfer(self.db, 1, 2, "all", deposit=True),
        )
        statuses = sorted(status for status, _amount in results)
        self.assertEqual(statuses, ["invalid", "ok"])
        cash, bank = await _cash_bank(self.db, 1, 2)
        self.assertEqual(cash, 0)
        self.assertEqual(bank, 100)


class AtomicSellTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = await _make_db()

    async def asyncTearDown(self):
        await self.db._conn.close()

    async def test_vend_au_prix_moitie_de_la_boutique(self):
        await self.db._conn.execute(
            "INSERT INTO inventory (guild_id,user_id,item_name,quantity) VALUES (1,2,'Épée',3)"
        )
        await self.db._conn.execute(
            "INSERT INTO shop_items (guild_id,name,price) VALUES (1,'Épée',100)"
        )
        await self.db._conn.commit()

        status, price = await economy.atomic_sell(self.db, 1, 2, "Épée")

        self.assertEqual(status, "ok")
        self.assertEqual(price, 50)
        self.assertEqual((await _cash_bank(self.db, 1, 2))[0], 50)
        cur = await self.db._conn.execute(
            "SELECT quantity FROM inventory WHERE guild_id=1 AND user_id=2 AND item_name='Épée'"
        )
        row = await cur.fetchone()
        await cur.close()
        self.assertEqual(row["quantity"], 2)

    async def test_prix_par_defaut_si_absent_de_la_boutique(self):
        await self.db._conn.execute(
            "INSERT INTO inventory (guild_id,user_id,item_name,quantity) VALUES (1,2,'Mystère',1)"
        )
        await self.db._conn.commit()

        status, price = await economy.atomic_sell(self.db, 1, 2, "Mystère")

        self.assertEqual(status, "ok")
        self.assertEqual(price, 10)

    async def test_objet_absent_est_rejete(self):
        status, price = await economy.atomic_sell(self.db, 1, 2, "Rien")
        self.assertEqual(status, "missing")
        self.assertEqual(price, 0)

    async def test_derniere_unite_est_supprimee_de_linventaire(self):
        await self.db._conn.execute(
            "INSERT INTO inventory (guild_id,user_id,item_name,quantity) VALUES (1,2,'Unique',1)"
        )
        await self.db._conn.commit()

        await economy.atomic_sell(self.db, 1, 2, "Unique")

        cur = await self.db._conn.execute(
            "SELECT COUNT(*) AS n FROM inventory WHERE guild_id=1 AND user_id=2 AND item_name='Unique'"
        )
        row = await cur.fetchone()
        await cur.close()
        self.assertEqual(row["n"], 0)


class AtomicGambleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = await _make_db()

    async def asyncTearDown(self):
        await self.db._conn.close()

    async def test_victoire_credite_le_montant(self):
        await _seed_economy(self.db, 1, 2, cash=100)
        status = await economy.atomic_gamble(self.db, 1, 2, 30, win=True)
        self.assertEqual(status, "ok")
        self.assertEqual((await _cash_bank(self.db, 1, 2))[0], 130)

    async def test_defaite_debite_le_montant(self):
        await _seed_economy(self.db, 1, 2, cash=100)
        status = await economy.atomic_gamble(self.db, 1, 2, 30, win=False)
        self.assertEqual(status, "ok")
        self.assertEqual((await _cash_bank(self.db, 1, 2))[0], 70)

    async def test_solde_insuffisant_est_refuse(self):
        await _seed_economy(self.db, 1, 2, cash=10)
        status = await economy.atomic_gamble(self.db, 1, 2, 9999, win=False)
        self.assertEqual(status, "insufficient")
        self.assertEqual((await _cash_bank(self.db, 1, 2))[0], 10)

    async def test_montant_negatif_ou_nul_est_invalide(self):
        status = await economy.atomic_gamble(self.db, 1, 2, 0, win=True)
        self.assertEqual(status, "invalid")

    async def test_mises_concurrentes_ne_rendent_jamais_le_solde_negatif(self):
        """Avant le correctif d'origine : deux mises concurrentes lisaient toutes les
        deux un solde suffisant avant qu'aucune n'écrive, rendant le solde négatif."""
        await _seed_economy(self.db, 1, 2, cash=100)
        results = await asyncio.gather(
            economy.atomic_gamble(self.db, 1, 2, 80, win=False),
            economy.atomic_gamble(self.db, 1, 2, 80, win=False),
        )
        self.assertEqual(sorted(results), ["insufficient", "ok"])
        cash, _bank = await _cash_bank(self.db, 1, 2)
        self.assertGreaterEqual(cash, 0)
        self.assertEqual(cash, 20)


class AtomicRobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = await _make_db()

    async def asyncTearDown(self):
        await self.db._conn.close()

    async def test_cible_trop_pauvre_est_refusee_sans_effet(self):
        await _seed_economy(self.db, 1, 10, cash=500)
        await _seed_economy(self.db, 1, 20, cash=10)
        kind, value = await economy.atomic_rob(self.db, 1, 10, 20)
        self.assertEqual(kind, "poor")
        self.assertEqual(value, 0)

    async def test_cooldown_actif_bloque_le_vol(self):
        import time
        await _seed_economy(self.db, 1, 10, cash=500, last_rob=int(time.time()))
        await _seed_economy(self.db, 1, 20, cash=500)
        kind, value = await economy.atomic_rob(self.db, 1, 10, 20)
        self.assertEqual(kind, "cooldown")
        self.assertGreater(value, 0)

    async def test_succes_ou_echec_est_toujours_atomique_et_borne(self):
        """success débite exactement la cible et crédite exactement le voleur ; failed
        peut débiter le voleur (amende) mais jamais en dessous de zéro."""
        await _seed_economy(self.db, 1, 10, cash=500)
        await _seed_economy(self.db, 1, 20, cash=500)
        kind, value = await economy.atomic_rob(self.db, 1, 10, 20)
        self.assertIn(kind, {"success", "failed"})
        thief_cash, _ = await _cash_bank(self.db, 1, 10)
        victim_cash, _ = await _cash_bank(self.db, 1, 20)
        self.assertGreaterEqual(thief_cash, 0)
        self.assertGreaterEqual(victim_cash, 0)
        if kind == "success":
            self.assertEqual(victim_cash, 500 - value)
            self.assertEqual(thief_cash, 500 + value)
        else:
            self.assertEqual(thief_cash, 500 - value)
            self.assertEqual(victim_cash, 500)

    async def test_comptes_absents_sont_crees_a_zero(self):
        kind, value = await economy.atomic_rob(self.db, 1, 10, 20)
        self.assertEqual(kind, "poor")
        self.assertEqual(value, 0)


if __name__ == "__main__":
    unittest.main()
