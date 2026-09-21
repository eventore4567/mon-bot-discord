"""cogs/levels.py — trois chemins d'affichage de niveau/rang n'appliquaient
jamais le garde-fou _niveaux_actifs (même classe de bug déjà trouvée et
corrigée pour /profile, voir tests/test_profile_niveaux_actifs.py) :
build_level_embed() (bouton "📈 Niveau" sous /stats), build_ranks_embed()
(bouton "🏆 Classement" sous /stats) et /leaderboard-levels elle-même.
build_level_panneau() (utilisée par /level et /rank) appliquait déjà
correctement ce garde-fou — non concerné par ce correctif, non retesté ici."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.levels import Levels
from utils import sentrix_panels as panels


def _fake_stats(**overrides):
    base = {
        "current_level": 7,
        "current_level_xp": 120,
        "required_xp": 500,
        "progress_pct": 24,
        "rank": 3,
        "is_ranked": True,
        "message_count": 42,
        "next_level_role": None,
        "all_roles_obtained": False,
        "remaining_levels": 0,
        "next_level_requirement": 0,
    }
    base.update(overrides)
    return base


def _fake_ranks(**overrides):
    base = {
        "xp_rank": 3,
        "message_rank": 5,
        "voice_rank": 8,
        "economy_rank": 2,
        "reputation_rank": 6,
    }
    base.update(overrides)
    return base


class _FakeRole:
    def __init__(self, name):
        self.name = name


class _FakeGuild:
    id = 555


class _FakeMember:
    id = 2002
    display_name = "Membre Test"
    display_avatar = SimpleNamespace(url="https://example.com/a.png")


def _make_cog(*, niveaux_actifs: bool, economie_active: bool = True):
    bot = SimpleNamespace(db=SimpleNamespace(
        get_stats_settings=AsyncMock(return_value={
            "color": 0x123456,
            "footer": "SentriX",
            "title_stats": "Stats de {display_name}",
            "show_messages": True,
            "show_voice": False,
            "show_economy": True,
            "show_reputation": False,
            "show_join_date": False,
            "show_next_role": True,
            "buttons_visible": True,
            "economy_emoji": "coin",
        }),
    ))
    cog = Levels.__new__(Levels)
    cog.bot = bot
    cog._niveaux_actifs = AsyncMock(return_value=niveaux_actifs)
    cog._economie_active = AsyncMock(return_value=economie_active)
    return cog


class BuildLevelEmbedTests(unittest.IsolatedAsyncioTestCase):
    async def test_masque_le_niveau_quand_desactive(self):
        cog = _make_cog(niveaux_actifs=False)
        with patch("cogs.levels.stats_service.get_member_statistics", AsyncMock(return_value=_fake_stats())):
            embed = await cog.build_level_embed(_FakeGuild(), _FakeMember())

        self.assertIn("désactivé", embed.description.casefold())
        self.assertEqual(embed.fields, [])

    async def test_affiche_le_niveau_quand_actifs(self):
        cog = _make_cog(niveaux_actifs=True)
        with patch("cogs.levels.stats_service.get_member_statistics", AsyncMock(return_value=_fake_stats())):
            embed = await cog.build_level_embed(_FakeGuild(), _FakeMember())

        noms = [f.name for f in embed.fields]
        self.assertIn("Niveau actuel", noms)


class BuildRanksEmbedTests(unittest.IsolatedAsyncioTestCase):
    async def test_masque_completement_le_rang_de_niveau_quand_desactive(self):
        cog = _make_cog(niveaux_actifs=False)
        with patch("cogs.levels.stats_service.get_member_statistics", AsyncMock(return_value=_fake_stats())), \
             patch("cogs.levels.stats_service.get_category_ranks", AsyncMock(return_value=_fake_ranks())):
            embed = await cog.build_ranks_embed(_FakeGuild(), _FakeMember())

        noms = [f.name for f in embed.fields]
        self.assertNotIn("XP / Niveau", noms)

    async def test_les_autres_classements_restent_affiches_si_leurs_modules_sont_actifs(self):
        cog = _make_cog(niveaux_actifs=False, economie_active=True)
        with patch("cogs.levels.stats_service.get_member_statistics", AsyncMock(return_value=_fake_stats())), \
             patch("cogs.levels.stats_service.get_category_ranks", AsyncMock(return_value=_fake_ranks())):
            embed = await cog.build_ranks_embed(_FakeGuild(), _FakeMember())

        champs = {f.name: f.value for f in embed.fields}
        self.assertEqual(champs["Messages"], "#5")
        self.assertEqual(champs["Économie"], "#2")

    async def test_masque_aussi_economie_quand_module_inactif(self):
        cog = _make_cog(niveaux_actifs=False, economie_active=False)
        with patch("cogs.levels.stats_service.get_member_statistics", AsyncMock(return_value=_fake_stats())), \
             patch("cogs.levels.stats_service.get_category_ranks", AsyncMock(return_value=_fake_ranks())):
            embed = await cog.build_ranks_embed(_FakeGuild(), _FakeMember())

        noms = [f.name for f in embed.fields]
        self.assertNotIn("XP / Niveau", noms)
        self.assertNotIn("Économie", noms)

    async def test_affiche_le_rang_de_niveau_quand_actifs(self):
        cog = _make_cog(niveaux_actifs=True)
        with patch("cogs.levels.stats_service.get_member_statistics", AsyncMock(return_value=_fake_stats())), \
             patch("cogs.levels.stats_service.get_category_ranks", AsyncMock(return_value=_fake_ranks())):
            embed = await cog.build_ranks_embed(_FakeGuild(), _FakeMember())

        xp_field = next(f for f in embed.fields if f.name == "XP / Niveau")
        self.assertEqual(xp_field.value, "#3")


class LeaderboardLevelsCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_affiche_un_panneau_desactive_sans_toucher_la_base(self):
        cog = _make_cog(niveaux_actifs=False)
        cog.bot.db.fetchall = AsyncMock(side_effect=AssertionError("ne doit jamais lire la table levels"))
        ctx = SimpleNamespace(
            guild=_FakeGuild(), author=_FakeMember(), interaction=None, send=AsyncMock(),
        )

        await Levels.leaderboard_levels.callback(cog, ctx)

        ctx.send.assert_awaited()
        panneau = ctx.send.await_args.kwargs.get("view") or ctx.send.await_args.args[0]
        self.assertIsInstance(panneau, panels.Panneau)
        self.assertIn("désactivé", panels.texte_complet(panneau).casefold())

    async def test_fonctionne_normalement_quand_actifs(self):
        cog = _make_cog(niveaux_actifs=True)
        cog.bot.db.fetchall = AsyncMock(return_value=[])
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id=555, name="Serveur Test"),
            author=_FakeMember(), interaction=None, send=AsyncMock(),
        )

        await Levels.leaderboard_levels.callback(cog, ctx)

        cog.bot.db.fetchall.assert_awaited_once()
        ctx.send.assert_awaited()


class StatsDisabledModulesVisibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_stats_ne_montre_ni_niveaux_ni_economie_si_inactifs(self):
        cog = _make_cog(niveaux_actifs=False, economie_active=False)
        stats = _fake_stats(
            wallet=123,
            bank=456,
            total_money=579,
            voice_time=0,
            reputation=0,
            joined_at=None,
        )
        with patch("cogs.levels.stats_service.get_member_statistics", AsyncMock(return_value=stats)):
            embed = await cog.build_stats_embed(_FakeGuild(), _FakeMember())

        noms = [f.name for f in embed.fields]
        self.assertNotIn("📈 Niveau", noms)
        self.assertNotIn("📈 Niveaux", noms)
        self.assertNotIn("✨ Progression", noms)
        self.assertNotIn("🎭 Prochain rôle", noms)
        self.assertNotIn("💰 Économie", noms)

    def test_vue_stats_retire_les_boutons_des_modules_inactifs(self):
        cog = _make_cog(niveaux_actifs=False, economie_active=False)
        view = __import__("cogs.levels", fromlist=["StatsView"]).StatsView(
            cog,
            _FakeGuild(),
            _FakeMember(),
            author_id=1,
            levels_enabled=False,
            economy_enabled=False,
        )
        custom_ids = {getattr(child, "custom_id", None) for child in view.children}
        self.assertNotIn("statsnav:level", custom_ids)
        self.assertNotIn("statsnav:eco", custom_ids)
        self.assertIn("statsnav:stats", custom_ids)
        self.assertIn("statsnav:rank", custom_ids)


if __name__ == "__main__":
    unittest.main()
