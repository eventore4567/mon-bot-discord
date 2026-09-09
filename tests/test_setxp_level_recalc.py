"""`+set-xp` écrivait directement la colonne `xp` sans jamais recalculer `level` —
exactement le bug que `_apply_xp_delta` a été créé pour corriger sur `+add-xp` (voir
son propre docstring dans cogs/levels.py), resté présent sur `+set-xp`. Un admin qui
faisait `+set-xp @membre 5000` sur un membre au niveau 0 obtenait `xp=5000, level=0`
— un XP largement au-dessus du seuil du niveau courant sans jamais monter de niveau,
l'exacte anomalie que `+levelcheck`/`+levelrepair` existent pour détecter et réparer
manuellement après coup.

Corrigé en calculant le delta nécessaire pour atteindre la valeur demandée puis en
passant par `_apply_xp_delta` (la même méthode déjà utilisée par `+add-xp` et le gain
passif), qui recalcule toujours le niveau correctement.

Test d'exécution réel : vraie base SQLite temporaire, vrai cog Levels."""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database
from cogs.levels import Levels
from utils import stats_service


class _FakeBot:
    def __init__(self, db: Database):
        self.db = db


class SetXpLevelRecalcTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self._tmpdir.name, "sentrix-test.db"))
        await self.db.connect()
        self.bot = _FakeBot(self.db)
        self.cog = Levels.__new__(Levels)
        self.cog.bot = self.bot
        self.cog._xp_locks = {}
        self.guild_id, self.user_id = 1, 42
        await self.db.ensure_level(self.guild_id, self.user_id)

    async def asyncTearDown(self):
        await self.db._conn.close()
        self._tmpdir.cleanup()

    async def test_set_xp_recalcule_le_niveau_quand_la_valeur_depasse_le_seuil(self):
        """C'est exactement le bug rapporté : avant le correctif, xp=250 était écrit
        tel quel avec level toujours à 0, alors que 250 dépasse largement le seuil
        du niveau 0 (100 XP)."""
        needed_level_0 = stats_service.xp_required_for_level(0)  # 100
        needed_level_1 = stats_service.xp_required_for_level(1)  # 155
        target_xp = needed_level_0 + 150  # 250 : doit passer niveau 0 -> 1, reste 150

        await self.cog.set_xp.callback(self.cog, _fake_ctx(self.guild_id), _fake_member(self.user_id), target_xp)

        row = await self.db.get_level(self.guild_id, self.user_id)
        self.assertEqual(row["level"], 1)
        self.assertEqual(row["xp"], target_xp - needed_level_0)
        self.assertLess(row["xp"], needed_level_1)

    async def test_set_xp_en_dessous_du_seuil_ne_change_pas_le_niveau(self):
        """Non-régression : une valeur normale (sous le seuil) reste au niveau 0."""
        await self.cog.set_xp.callback(self.cog, _fake_ctx(self.guild_id), _fake_member(self.user_id), 50)

        row = await self.db.get_level(self.guild_id, self.user_id)
        self.assertEqual(row["level"], 0)
        self.assertEqual(row["xp"], 50)

    async def test_set_xp_negatif_est_ramene_a_zero(self):
        await self.cog.set_xp.callback(self.cog, _fake_ctx(self.guild_id), _fake_member(self.user_id), -50)

        row = await self.db.get_level(self.guild_id, self.user_id)
        self.assertEqual(row["xp"], 0)
        self.assertEqual(row["level"], 0)


def _fake_ctx(guild_id: int):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    return SimpleNamespace(guild=SimpleNamespace(id=guild_id), interaction=None, send=AsyncMock())


def _fake_member(user_id: int):
    from types import SimpleNamespace
    return SimpleNamespace(id=user_id, bot=False, mention=f"<@{user_id}>")


if __name__ == "__main__":
    unittest.main()
