"""cogs/visual_experience_v5.py::build_status_embed — Core V2, Phase 4 : le
corps de la fonction n'est plus que la mise en forme Discord au-dessus de
services/status.py::compute_health_snapshot(), déjà testé sans Discord dans
tests/test_services_status.py. Ce test vérifie le CÂBLAGE : les champs de
l'embed reflètent bien la sonde de santé."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.visual_experience_v5 import build_status_embed


def _fake_bot(*, latency=0.1, db_row={"ok": 1}, ai=True, music=True, command_count=42):
    cogs = {}
    if ai:
        cogs["Ai"] = object()
    if music:
        cogs["Music"] = object()
    return SimpleNamespace(
        latency=latency,
        db=SimpleNamespace(fetchone=AsyncMock(return_value=db_row)),
        get_cog=lambda name: cogs.get(name),
        commands=[object()] * command_count,
        user=None,
    )


class BuildStatusEmbedWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_tout_operationnel_est_vert_et_montre_les_bons_champs(self):
        bot = _fake_bot(ai=True, music=True, latency=0.1, command_count=42)

        embed = await build_status_embed(bot, guild=None)

        self.assertEqual(embed.colour.value, 0x2FBF71)
        champs = {f.name: f.value for f in embed.fields}
        self.assertEqual(champs["Discord"], "En ligne • 100 ms")
        self.assertEqual(champs["Base"], "Opérationnelle")
        self.assertEqual(champs["Services"], "3/3 opérationnels")
        self.assertEqual(champs["IA"], "Disponible")
        self.assertEqual(champs["Musique"], "Disponible")
        self.assertEqual(champs["Commandes"], "42")

    async def test_service_indisponible_est_orange(self):
        bot = _fake_bot(ai=False, music=True)

        embed = await build_status_embed(bot, guild=None)

        self.assertEqual(embed.colour.value, 0xF0B232)
        champs = {f.name: f.value for f in embed.fields}
        self.assertEqual(champs["IA"], "Indisponible")
        self.assertEqual(champs["Services"], "2/3 opérationnels")


if __name__ == "__main__":
    unittest.main()
