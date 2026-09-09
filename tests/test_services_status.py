"""services/status.py::compute_health_snapshot — Core V2, Phase 4.

Extrait de cogs/visual_experience_v5.py::build_status_embed() : le calcul de
santé (latence, base joignable, cogs IA/Musique chargés, seuil "nominal")
n'a plus besoin d'un vrai bot Discord ni d'une vraie base de données pour
être vérifié."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from services import status as status_service


def _fake_bot(*, latency=0.1, db_row={"ok": 1}, db_raises=None, ai=True, music=True, command_count=42):
    fetchone = AsyncMock(side_effect=db_raises) if db_raises else AsyncMock(return_value=db_row)
    cogs = {}
    if ai:
        cogs["Ai"] = object()
    if music:
        cogs["Music"] = object()
    return SimpleNamespace(
        latency=latency,
        db=SimpleNamespace(fetchone=fetchone),
        get_cog=lambda name: cogs.get(name),
        commands=[object()] * command_count,
    )


class HealthSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_tout_operationnel_est_nominal(self):
        bot = _fake_bot(latency=0.1, ai=True, music=True)

        snapshot = await status_service.compute_health_snapshot(bot)

        self.assertEqual(snapshot.latency_ms, 100)
        self.assertTrue(snapshot.database_ok)
        self.assertTrue(snapshot.ai_ok)
        self.assertTrue(snapshot.music_ok)
        self.assertEqual(snapshot.healthy_count, 3)
        self.assertTrue(snapshot.is_nominal)
        self.assertEqual(snapshot.command_count, 42)

    async def test_base_injoignable_ne_leve_jamais(self):
        bot = _fake_bot(db_raises=RuntimeError("connexion refusée"))

        snapshot = await status_service.compute_health_snapshot(bot)

        self.assertFalse(snapshot.database_ok)
        self.assertEqual(snapshot.healthy_count, 2)
        self.assertFalse(snapshot.is_nominal)

    async def test_ligne_sans_ok_est_traitee_comme_indisponible(self):
        bot = _fake_bot(db_row={"ok": 0})

        snapshot = await status_service.compute_health_snapshot(bot)

        self.assertFalse(snapshot.database_ok)

    async def test_ai_ou_musique_absents_ne_sont_pas_nominaux(self):
        bot = _fake_bot(ai=False, music=True)

        snapshot = await status_service.compute_health_snapshot(bot)

        self.assertFalse(snapshot.ai_ok)
        self.assertEqual(snapshot.healthy_count, 2)
        self.assertFalse(snapshot.is_nominal)

    async def test_latence_elevee_n_est_pas_nominale_meme_si_tout_est_charge(self):
        bot = _fake_bot(latency=0.5, ai=True, music=True)  # 500ms >= 300ms

        snapshot = await status_service.compute_health_snapshot(bot)

        self.assertEqual(snapshot.healthy_count, 3)
        self.assertFalse(snapshot.is_nominal)

    async def test_latence_juste_sous_le_seuil_est_nominale(self):
        bot = _fake_bot(latency=0.299, ai=True, music=True)

        snapshot = await status_service.compute_health_snapshot(bot)

        self.assertTrue(snapshot.is_nominal)


if __name__ == "__main__":
    unittest.main()
