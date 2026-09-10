"""services/levels.py::apply_xp_delta() — extrait de cogs/levels.py::
Levels._apply_xp_delta(), le point d'entrée unique partagé par le gain d'XP
passif, +add-xp et +set-xp (voir tests/test_setxp_level_recalc.py pour le
bug historique que cette fonction corrige : +set-xp écrivait `xp` sans
recalculer `level`). Comportement inchangé par l'extraction — ces tests
couvrent la fonction directement plutôt qu'à travers une commande, contre
une vraie base SQLite en mémoire (le point même de cette fonction est le
calcul lecture-modification-écriture sous verrou, qu'un mock ne vérifie pas
fidèlement)."""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database
from services import levels as levels_service
from utils import stats_service


class ApplyXpDeltaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self._tmpdir.name, "sentrix-test.db"))
        await self.db.connect()
        self.locks: dict[tuple[int, int], asyncio.Lock] = {}
        self.guild_id, self.user_id = 1, 42

    async def asyncTearDown(self):
        await self.db._conn.close()
        self._tmpdir.cleanup()

    async def test_cree_le_compte_niveau_sil_nexiste_pas_encore(self):
        new_xp, level, leveled_up = await levels_service.apply_xp_delta(
            self.db, self.locks, self.guild_id, self.user_id, 50
        )
        self.assertEqual((new_xp, level, leveled_up), (50, 0, False))

    async def test_ajoute_de_lxp_sans_franchir_le_seuil(self):
        await levels_service.apply_xp_delta(self.db, self.locks, self.guild_id, self.user_id, 30)
        new_xp, level, leveled_up = await levels_service.apply_xp_delta(
            self.db, self.locks, self.guild_id, self.user_id, 20
        )
        self.assertEqual(new_xp, 50)
        self.assertEqual(level, 0)
        self.assertFalse(leveled_up)

    async def test_franchit_un_seuil_et_recalcule_le_niveau(self):
        needed_level_0 = stats_service.xp_required_for_level(0)  # 100
        new_xp, level, leveled_up = await levels_service.apply_xp_delta(
            self.db, self.locks, self.guild_id, self.user_id, needed_level_0 + 20
        )
        self.assertEqual(level, 1)
        self.assertEqual(new_xp, 20)
        self.assertTrue(leveled_up)

    async def test_franchit_plusieurs_niveaux_dun_coup(self):
        total = sum(stats_service.xp_required_for_level(n) for n in range(3)) + 10
        _new_xp, level, leveled_up = await levels_service.apply_xp_delta(
            self.db, self.locks, self.guild_id, self.user_id, total
        )
        self.assertEqual(level, 3)
        self.assertTrue(leveled_up)

    async def test_retrait_dxp_ne_fait_jamais_descendre_le_niveau(self):
        needed_level_0 = stats_service.xp_required_for_level(0)
        await levels_service.apply_xp_delta(self.db, self.locks, self.guild_id, self.user_id, needed_level_0 + 20)
        new_xp, level, leveled_up = await levels_service.apply_xp_delta(
            self.db, self.locks, self.guild_id, self.user_id, -1000
        )
        self.assertEqual(new_xp, 0)
        self.assertEqual(level, 1)
        self.assertFalse(leveled_up)

    async def test_ecrit_bien_en_base(self):
        await levels_service.apply_xp_delta(self.db, self.locks, self.guild_id, self.user_id, 60)
        row = await self.db.get_level(self.guild_id, self.user_id)
        self.assertEqual(row["xp"], 60)
        self.assertEqual(row["level"], 0)

    async def test_gains_concurrents_du_meme_membre_ne_sont_jamais_perdus(self):
        """Avant le verrou par membre : deux tâches lisaient le même XP de départ et la
        dernière écriture gagnait, perdant l'autre gain — reproduit ici en lançant deux
        deltas en parallèle sur le même membre."""
        results = await asyncio.gather(
            levels_service.apply_xp_delta(self.db, self.locks, self.guild_id, self.user_id, 40),
            levels_service.apply_xp_delta(self.db, self.locks, self.guild_id, self.user_id, 40),
        )
        row = await self.db.get_level(self.guild_id, self.user_id)
        self.assertEqual(row["xp"], 80)
        self.assertEqual({r[0] for r in results}, {40, 80})

    async def test_verrou_est_bien_par_membre_pas_partage_entre_membres(self):
        other_user_id = 99
        results = await asyncio.gather(
            levels_service.apply_xp_delta(self.db, self.locks, self.guild_id, self.user_id, 30),
            levels_service.apply_xp_delta(self.db, self.locks, self.guild_id, other_user_id, 30),
        )
        self.assertEqual(results[0][0], 30)
        self.assertEqual(results[1][0], 30)
        self.assertIn((self.guild_id, self.user_id), self.locks)
        self.assertIn((self.guild_id, other_user_id), self.locks)


if __name__ == "__main__":
    unittest.main()
