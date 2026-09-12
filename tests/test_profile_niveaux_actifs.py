"""cogs/profile_oxyde_runtime.py::build_page — vérification COMPORTEMENTALE
(pas seulement textuelle) que le garde-fou niveaux_actifs masque réellement les
champs Niveau/XP/Rang de +profile quand le système de niveaux est désactivé.

Bug réel trouvé pendant Core V2 Phase 4 : la commande +profile réellement
exécutée (cogs/profile_oxyde_runtime.py, qui remplace le corps de la commande
définie dans cogs/levels.py au démarrage) n'appliquait AUCUN garde-fou —
+profile affichait Niveau/XP/Rang même sur un serveur ayant désactivé les
niveaux, alors que tests/test_niveaux_desactives.py croyait ce cas couvert en
vérifiant, à tort, le corps MORT de cogs/levels.py::profile (jamais exécuté en
production). Ces tests appellent directement build_page() avec un cog Levels
factice, sans jamais toucher au texte source."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from cogs import profile_oxyde_runtime


def _fake_snapshot_data():
    return {
        "stats": {
            "current_level": 12, "total_xp": 4321, "rank": 3, "is_ranked": True,
            "wallet": 500, "bank": 1500, "message_count": 42, "voice_time": 3600, "reputation": 5,
        },
        "progression": {"daily_streak": 2, "season_id": "s1", "season_xp": 0},
        "bio": None,
        "ranks": {"xp_rank": 3, "message_rank": 7, "economy_rank": 2},
        "season_rank": 1,
    }


class _FakeMember:
    def __init__(self, id=2002):
        self.id = id
        self.display_name = "Membre Test"
        self.mention = f"<@{id}>"
        self.display_avatar = SimpleNamespace(url="https://example.com/a.png")
        self.created_at = discord.utils.utcnow()
        self.joined_at = None
        self.guild_permissions = SimpleNamespace(manage_messages=False, moderate_members=False)


class _FakeLevelsCog:
    def __init__(self, actifs: bool):
        self._actifs = actifs

    async def _niveaux_actifs(self, guild_id):
        return self._actifs


def _fake_bot(*, levels_cog=None):
    return SimpleNamespace(
        user=SimpleNamespace(display_avatar=SimpleNamespace(url="https://example.com/bot.png")),
        get_cog=lambda name: levels_cog if name == "Levels" else None,
    )


class OverviewPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_masque_la_progression_quand_desactive(self):
        bot = _fake_bot(levels_cog=_FakeLevelsCog(False))
        guild = SimpleNamespace(id=555)
        member = _FakeMember()

        with patch.object(profile_oxyde_runtime, "_snapshot", AsyncMock(return_value=_fake_snapshot_data())):
            embed = await profile_oxyde_runtime.build_page(bot, guild, member, member.id, "overview")

        progression = next(f for f in embed.fields if f.name == "Progression")
        self.assertEqual(progression.value, "Niveaux désactivés sur ce serveur.")

    async def test_affiche_la_progression_quand_actifs(self):
        bot = _fake_bot(levels_cog=_FakeLevelsCog(True))
        guild = SimpleNamespace(id=555)
        member = _FakeMember()

        with patch.object(profile_oxyde_runtime, "_snapshot", AsyncMock(return_value=_fake_snapshot_data())):
            embed = await profile_oxyde_runtime.build_page(bot, guild, member, member.id, "overview")

        progression = next(f for f in embed.fields if f.name == "Progression")
        self.assertIn("Niveau", progression.value)
        self.assertIn("12", progression.value)

    async def test_les_autres_champs_restent_affiches_quand_desactive(self):
        """Économie/Activité/Compte ne dépendent pas des niveaux — ils restent."""
        bot = _fake_bot(levels_cog=_FakeLevelsCog(False))
        guild = SimpleNamespace(id=555)
        member = _FakeMember()

        with patch.object(profile_oxyde_runtime, "_snapshot", AsyncMock(return_value=_fake_snapshot_data())):
            embed = await profile_oxyde_runtime.build_page(bot, guild, member, member.id, "overview")

        noms = [f.name for f in embed.fields]
        self.assertIn("Économie", noms)
        self.assertIn("Activité", noms)
        self.assertIn("Compte", noms)


class RankingsPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_masque_le_rang_de_niveau_quand_desactive(self):
        bot = _fake_bot(levels_cog=_FakeLevelsCog(False))
        guild = SimpleNamespace(id=555)
        member = _FakeMember()

        with patch.object(profile_oxyde_runtime, "_snapshot", AsyncMock(return_value=_fake_snapshot_data())):
            embed = await profile_oxyde_runtime.build_page(bot, guild, member, member.id, "rankings")

        self.assertIn("Niveau / XP\n**Désactivé sur ce serveur**", embed.description)
        self.assertNotIn("**#3**", embed.description)

    async def test_affiche_le_rang_de_niveau_quand_actifs(self):
        bot = _fake_bot(levels_cog=_FakeLevelsCog(True))
        guild = SimpleNamespace(id=555)
        member = _FakeMember()

        with patch.object(profile_oxyde_runtime, "_snapshot", AsyncMock(return_value=_fake_snapshot_data())):
            embed = await profile_oxyde_runtime.build_page(bot, guild, member, member.id, "rankings")

        self.assertIn("Niveau / XP\n**#3**", embed.description)

    async def test_le_rang_de_messages_reste_affiche_quand_desactive(self):
        bot = _fake_bot(levels_cog=_FakeLevelsCog(False))
        guild = SimpleNamespace(id=555)
        member = _FakeMember()

        with patch.object(profile_oxyde_runtime, "_snapshot", AsyncMock(return_value=_fake_snapshot_data())):
            embed = await profile_oxyde_runtime.build_page(bot, guild, member, member.id, "rankings")

        self.assertIn("Messages\n**#7**", embed.description)


class FailOpenTests(unittest.IsolatedAsyncioTestCase):
    async def test_sans_cog_levels_charge_les_niveaux_sont_consideres_actifs(self):
        """Fail-open, cohérent avec le comportement de _niveaux_actifs lui-même
        (cogs/levels.py) quand une de ses propres vérifications échoue."""
        bot = _fake_bot(levels_cog=None)
        guild = SimpleNamespace(id=555)
        member = _FakeMember()

        with patch.object(profile_oxyde_runtime, "_snapshot", AsyncMock(return_value=_fake_snapshot_data())):
            embed = await profile_oxyde_runtime.build_page(bot, guild, member, member.id, "overview")

        progression = next(f for f in embed.fields if f.name == "Progression")
        self.assertIn("Niveau", progression.value)


if __name__ == "__main__":
    unittest.main()
