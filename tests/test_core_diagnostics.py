"""cogs/core_diagnostics.py — /corediag (Core V2, Phase 1).

Nommée /corediag et non /diagnostic pour ne pas ajouter une quatrième couche
à un callback déjà réécrit trois fois (docs/core-v2-audit-technical-debt.md
§7) — voir le docstring du cog pour le raisonnement complet. Ces tests
vérifient : accès réservé au propriétaire global, rendu sans plantage avec et
sans données d'observabilité, et classification correcte dans le catalogue de
commandes (jamais "other")."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.core_diagnostics import CoreDiagnostics
from cogs import help_complete
from core.observability import metrics
from utils.checks import BotPermissionError


class _FakeBot:
    def __init__(self):
        self.guilds = []
        self.latency = 0.042

    def is_ready(self):
        return True

    def is_closed(self):
        return False

    def walk_commands(self):
        return iter([])

    class tree:
        @staticmethod
        def get_commands():
            return []


def _fake_ctx(author_id: int):
    return SimpleNamespace(
        author=SimpleNamespace(id=author_id),
        guild=None,
        interaction=None,
        send=AsyncMock(),
    )


class OwnershipGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_le_decorateur_owner_only_est_bien_present(self):
        self.assertEqual(len(CoreDiagnostics.corediag.checks), 1)

    async def test_refuse_un_membre_qui_n_est_pas_proprietaire(self):
        """.callback() seul ne suffit pas : @checks.is_bot_owner() est un check
        discord.py, jamais appliqué par le callback lui-même — on appelle donc
        directement le prédicat, sans reconstruire toute la machinerie
        can_run()/Bot.can_run() de discord.py."""
        bot = _FakeBot()
        bot.db = SimpleNamespace(is_bot_creator=AsyncMock(return_value=False))
        ctx = SimpleNamespace(author=SimpleNamespace(id=999999), bot=bot)

        predicate = CoreDiagnostics.corediag.checks[0]
        with self.assertRaises(BotPermissionError):
            await predicate(ctx)

    async def test_autorise_le_proprietaire_global(self):
        bot = _FakeBot()
        bot.db = SimpleNamespace(is_bot_creator=AsyncMock(return_value=True))
        ctx = SimpleNamespace(author=SimpleNamespace(id=1), bot=bot)

        predicate = CoreDiagnostics.corediag.checks[0]
        self.assertTrue(await predicate(ctx))


class RenderingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        metrics.reset_for_tests()
        self.bot = _FakeBot()
        self.cog = CoreDiagnostics(self.bot)

    async def test_fonctionne_sans_donnees_d_observabilite(self):
        ctx = _fake_ctx(author_id=1)
        await CoreDiagnostics.corediag.callback(self.cog, ctx)
        ctx.send.assert_awaited()

    async def test_fonctionne_avec_des_donnees_d_observabilite(self):
        metrics.record("ban", "slash", 120.0, success=True)
        metrics.record("ban", "slash", 340.0, success=True)
        metrics.record_error("ban", "slash")

        ctx = _fake_ctx(author_id=1)
        await CoreDiagnostics.corediag.callback(self.cog, ctx)
        ctx.send.assert_awaited()

    async def test_plus_de_dix_commandes_ne_plante_pas(self):
        for i in range(15):
            metrics.record(f"cmd{i}", "prefix", 10.0, success=True)
        ctx = _fake_ctx(author_id=1)
        await CoreDiagnostics.corediag.callback(self.cog, ctx)
        ctx.send.assert_awaited()


class CatalogClassificationTests(unittest.TestCase):
    def test_corediag_n_est_jamais_classee_dans_autre(self):
        command = SimpleNamespace(qualified_name="corediag", cog=None)
        category = help_complete._category_for(command)
        self.assertNotEqual(category.key, "other")


if __name__ == "__main__":
    unittest.main()
