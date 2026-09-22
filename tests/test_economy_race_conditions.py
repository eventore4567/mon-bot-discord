"""`/gamble`, `/rob`, `/deposit`, `/withdraw`, `/banque` lisaient le solde puis
écrivaient séparément, SANS `Database._economy_lock` — contrairement à `/pay`,
`/daily`, `/weekly`, `/work` et `/buy`, tous protégés (voir le commentaire de
`_economy_lock` lui-même : "paiement, daily, weekly, work, réputation"). Deux appels
concurrents (double-clic, ou deux commandes lancées presque en même temps) passaient
tous les deux la vérification de solde avant qu'aucun n'ait écrit :

- `/gamble` : deux mises simultanées sur un solde insuffisant pour les DEUX pouvaient
  toutes les deux être acceptées, rendant le solde négatif.
- `/rob` : deux voleurs différents pouvaient voler la même victime en même temps,
  la rendant négative.
- `/deposit`/`/withdraw`/`/banque` : deux dépôts 'all' concurrents pouvaient
  dupliquer de l'argent entre cash et banque.

Corrigé en ajoutant Database.gamble()/attempt_rob()/move_cash_bank(), qui vérifient
ET écrivent dans la même section critique (_economy_lock), exactement comme
pay_member()/claim_timed_reward() le font déjà pour /pay et /daily/weekly/work.

Tests d'exécution réels : vraie base SQLite temporaire, vraies coroutines lancées
concurremment via asyncio.gather (pas une simulation)."""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database


class EconomyRaceConditionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self._tmpdir.name, "sentrix-test.db"))
        await self.db.connect()
        self.guild_id = 1

    async def asyncTearDown(self):
        await self.db._conn.close()
        self._tmpdir.cleanup()

    async def _set_cash(self, user_id: int, cash: int, bank: int = 0):
        await self.db.ensure_economy(self.guild_id, user_id)
        await self.db.execute(
            "UPDATE economy SET cash = ?, bank = ? WHERE guild_id = ? AND user_id = ?",
            (cash, bank, self.guild_id, user_id),
        )

    async def test_gamble_concurrent_ne_rend_jamais_le_solde_negatif(self):
        """C'est exactement le bug rapporté : sans le correctif, deux mises de 100
        sur un solde de 100 sont TOUTES LES DEUX acceptées (solde final -100)."""
        user_id = 42
        await self._set_cash(user_id, 100)

        results = await asyncio.gather(
            self.db.gamble(self.guild_id, user_id, 100, False),
            self.db.gamble(self.guild_id, user_id, 100, False),
        )

        self.assertEqual(sorted(results), [False, True], "une seule des deux mises doit être acceptée")
        bal = await self.db.get_balance(self.guild_id, user_id)
        self.assertGreaterEqual(bal["cash"], 0, "le solde ne doit jamais devenir négatif")

    async def test_rob_concurrent_ne_vole_jamais_deux_fois_la_meme_victime(self):
        """C'est exactement le bug rapporté : deux voleurs concurrents sur une
        victime à 200 pouvaient tous les deux réussir, rendant son solde négatif."""
        victim_id, thief_a, thief_b = 100, 101, 102
        await self._set_cash(victim_id, 200)
        await self.db.ensure_economy(self.guild_id, thief_a)
        await self.db.ensure_economy(self.guild_id, thief_b)

        await asyncio.gather(
            self.db.attempt_rob(self.guild_id, thief_a, victim_id, success_chance=1.0, max_steal=200),
            self.db.attempt_rob(self.guild_id, thief_b, victim_id, success_chance=1.0, max_steal=200),
        )

        victim_bal = await self.db.get_balance(self.guild_id, victim_id)
        self.assertGreaterEqual(victim_bal["cash"], 0, "la victime ne doit jamais finir avec un solde négatif")

    async def test_deposit_concurrent_ne_duplique_jamais_argent(self):
        """C'est exactement le bug rapporté : deux 'deposit all' concurrents sur un
        cash de 100 pouvaient créditer 200 en banque à partir de 100 réels."""
        user_id = 200
        await self._set_cash(user_id, 100)

        await asyncio.gather(
            self.db.move_cash_bank(self.guild_id, user_id, "all", direction="deposit"),
            self.db.move_cash_bank(self.guild_id, user_id, "all", direction="deposit"),
        )

        bal = await self.db.get_balance(self.guild_id, user_id)
        self.assertEqual(bal["cash"] + bal["bank"], 100, "cash + banque doit rester égal au total de départ")
        self.assertGreaterEqual(bal["cash"], 0)

    async def test_withdraw_refuse_un_montant_superieur_au_solde_banque(self):
        user_id = 201
        await self._set_cash(user_id, 0, bank=50)

        result = await self.db.move_cash_bank(self.guild_id, user_id, "100", direction="withdraw")

        self.assertIsNone(result)
        bal = await self.db.get_balance(self.guild_id, user_id)
        self.assertEqual(bal["bank"], 50)

    async def test_gamble_refuse_normalement_un_solde_insuffisant(self):
        """Non-régression : le comportement normal (un seul appel, pas de course)
        continue de refuser une mise trop élevée."""
        user_id = 202
        await self._set_cash(user_id, 10)

        accepted = await self.db.gamble(self.guild_id, user_id, 100, True)

        self.assertFalse(accepted)
        bal = await self.db.get_balance(self.guild_id, user_id)
        self.assertEqual(bal["cash"], 10)


    async def test_rob_cooldown_est_persiste_en_base(self):
        thief_id, victim_id = 300, 301
        await self._set_cash(thief_id, 100)
        await self._set_cash(victim_id, 500)

        first = await self.db.attempt_rob(
            self.guild_id,
            thief_id,
            victim_id,
            success_chance=1.0,
            cooldown=3600,
        )
        self.assertEqual(first["outcome"], "success")

        second = await self.db.attempt_rob(
            self.guild_id,
            thief_id,
            victim_id,
            success_chance=1.0,
            cooldown=3600,
        )
        self.assertEqual(second["outcome"], "cooldown")
        self.assertGreater(second["remaining"], 0)

        row = await self.db.fetchone(
            "SELECT last_rob FROM economy WHERE guild_id = ? AND user_id = ?",
            (self.guild_id, thief_id),
        )
        self.assertGreater(int(row["last_rob"]), 0)

    async def test_rob_echec_ne_peut_jamais_rendre_le_voleur_negatif(self):
        thief_id, victim_id = 302, 303
        await self._set_cash(thief_id, 10)
        await self._set_cash(victim_id, 500)

        result = await self.db.attempt_rob(
            self.guild_id,
            thief_id,
            victim_id,
            success_chance=0.0,
            penalty_range=(100, 100),
            cooldown=0,
        )

        self.assertEqual(result["outcome"], "caught")
        self.assertEqual(result["penalty"], 10)
        bal = await self.db.get_balance(self.guild_id, thief_id)
        self.assertEqual(bal["cash"], 0)

    async def test_daily_concurrent_ne_peut_etre_reclame_quune_fois(self):
        user_id = 304
        results = await asyncio.gather(
            self.db.claim_timed_reward(
                self.guild_id, user_id, "last_daily", 200, 86400, "daily"
            ),
            self.db.claim_timed_reward(
                self.guild_id, user_id, "last_daily", 200, 86400, "daily"
            ),
        )

        self.assertEqual(sum(1 for ok, _remaining in results if ok), 1)
        bal = await self.db.get_balance(self.guild_id, user_id)
        self.assertEqual(bal["cash"], 200)

    async def test_achat_role_concurrent_ne_debite_quune_fois(self):
        user_id = 305
        await self._set_cash(user_id, 1000)
        cur = await self.db.execute(
            "INSERT INTO shop_items (guild_id, name, price, role_id) VALUES (?, ?, ?, ?)",
            (self.guild_id, "VIP", 400, 999),
        )
        item_id = cur.lastrowid

        results = await asyncio.gather(
            self.db.purchase_shop_item(self.guild_id, user_id, item_id),
            self.db.purchase_shop_item(self.guild_id, user_id, item_id),
        )
        statuses = sorted(status for status, _item in results)

        self.assertEqual(statuses, ["already_owned", "ok"])
        bal = await self.db.get_balance(self.guild_id, user_id)
        self.assertEqual(bal["cash"], 600)


if __name__ == "__main__":
    unittest.main()
