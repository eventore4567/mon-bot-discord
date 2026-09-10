"""services/profile.py — Core V2, Phase 4.

compute_badges() est cogs/profile_oxyde_runtime.py::_badges déplacé à
l'identique : ces tests verrouillent son comportement maintenant qu'il est
testable sans jamais construire un cog ni Discord. build_snapshot() reste un
point d'entrée fin vers community_v31._profile_snapshot() — vérifié ici via
délégation, sans dupliquer les tests déjà existants (si applicable) de cette
agrégation elle-même."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from services import profile as profile_service


class _FakeMember:
    def __init__(self, *, manage_messages=False, moderate_members=False, created_at=None):
        self.guild_permissions = SimpleNamespace(
            manage_messages=manage_messages, moderate_members=moderate_members,
        )
        self.created_at = created_at or discord.utils.utcnow()


class ComputeBadgesTests(unittest.TestCase):
    def test_aucun_badge_pour_un_membre_neutre(self):
        member = _FakeMember()
        badges = profile_service.compute_badges(member, {}, {})
        self.assertEqual(badges, [])

    def test_actif_a_partir_de_1000_messages(self):
        member = _FakeMember()
        badges = profile_service.compute_badges(member, {"message_count": 1000}, {})
        self.assertIn("Actif", badges)

    def test_pas_actif_sous_1000_messages(self):
        member = _FakeMember()
        badges = profile_service.compute_badges(member, {"message_count": 999}, {})
        self.assertNotIn("Actif", badges)

    def test_economiste_compte_portefeuille_plus_banque(self):
        member = _FakeMember()
        badges = profile_service.compute_badges(member, {"wallet": 6000, "bank": 4000}, {})
        self.assertIn("Économiste", badges)

    def test_saisonnier_des_que_season_xp_positif(self):
        member = _FakeMember()
        badges = profile_service.compute_badges(member, {}, {"season_xp": 1})
        self.assertIn("Saisonnier", badges)

    def test_staff_via_manage_messages(self):
        member = _FakeMember(manage_messages=True)
        badges = profile_service.compute_badges(member, {}, {})
        self.assertIn("Staff", badges)

    def test_staff_via_moderate_members(self):
        member = _FakeMember(moderate_members=True)
        badges = profile_service.compute_badges(member, {}, {})
        self.assertIn("Staff", badges)

    def test_veteran_a_partir_de_365_jours(self):
        member = _FakeMember(created_at=discord.utils.utcnow() - __import__("datetime").timedelta(days=400))
        badges = profile_service.compute_badges(member, {}, {})
        self.assertIn("Vétéran", badges)

    def test_pas_veteran_sous_365_jours(self):
        member = _FakeMember(created_at=discord.utils.utcnow() - __import__("datetime").timedelta(days=10))
        badges = profile_service.compute_badges(member, {}, {})
        self.assertNotIn("Vétéran", badges)

    def test_plafonne_a_cinq_badges(self):
        member = _FakeMember(
            manage_messages=True,
            created_at=discord.utils.utcnow() - __import__("datetime").timedelta(days=400),
        )
        badges = profile_service.compute_badges(
            member,
            {"message_count": 1000, "wallet": 10_000, "bank": 0},
            {"season_xp": 1},
        )
        self.assertEqual(len(badges), 5)


class BuildSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_delegue_a_community_v31_profile_snapshot(self):
        expected = {"stats": {}, "progression": {}, "bio": None, "ranks": {}, "season_rank": None}
        with patch(
            "services.profile.community_v31._profile_snapshot",
            AsyncMock(return_value=expected),
        ) as mocked:
            bot, guild, member = object(), object(), object()
            result = await profile_service.build_snapshot(bot, guild, member)

            mocked.assert_awaited_once_with(bot, guild, member)
            self.assertIs(result, expected)


if __name__ == "__main__":
    unittest.main()
