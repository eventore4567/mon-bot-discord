"""cogs/core_command_observability.py — Core V2, Phase 1.

Écoute passive : vérifie que le triplet on_command/on_command_completion/
on_command_error alimente bien core.observability.metrics, et que le nettoyeur
de listeners d'erreur préfixés (command_error_release_v41) ne le supprime pas
au passage — sans quoi les échecs ne seraient jamais comptés."""
from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.command_error_release_v41 import _dedupe_prefix_error_listeners
from cogs.core_command_observability import CoreCommandObservability
from core.observability import metrics


def _run(coro):
    return asyncio.run(coro)


class _FauxCtxSlash:
    interaction = object()
    command = SimpleNamespace(qualified_name="ban")


class _FauxCtxPrefix:
    interaction = None
    command = SimpleNamespace(qualified_name="ban")


class ListenerBehaviorTests(unittest.TestCase):
    def setUp(self):
        metrics.reset_for_tests()
        self.cog = CoreCommandObservability(bot=SimpleNamespace())

    def test_completion_prefixe_enregistre_un_succes(self):
        ctx = _FauxCtxPrefix()
        _run(self.cog.on_command(ctx))
        _run(self.cog.on_command_completion(ctx))

        stats = metrics.snapshot("ban")["ban"]
        self.assertEqual(stats.count, 1)
        self.assertEqual(stats.success_count, 1)

    def test_completion_slash_est_distinguee_en_interne_mais_fusionnee_a_l_affichage(self):
        _run(self.cog.on_command(_FauxCtxPrefix()))
        _run(self.cog.on_command_completion(_FauxCtxPrefix()))
        _run(self.cog.on_command(_FauxCtxSlash()))
        _run(self.cog.on_command_completion(_FauxCtxSlash()))

        stats = metrics.snapshot("ban")["ban"]
        self.assertEqual(stats.count, 2)
        self.assertEqual(stats.success_count, 2)

    def test_erreur_est_comptee_comme_echec(self):
        ctx = _FauxCtxPrefix()
        _run(self.cog.on_command_error(ctx, RuntimeError("boum")))

        stats = metrics.snapshot("ban")["ban"]
        self.assertEqual(stats.failure_count, 1)
        self.assertEqual(stats.success_count, 0)

    def test_commande_inconnue_ne_plante_pas(self):
        ctx = SimpleNamespace(interaction=None, command=None)
        _run(self.cog.on_command(ctx))
        _run(self.cog.on_command_completion(ctx))
        stats = metrics.snapshot("inconnue")["inconnue"]
        self.assertEqual(stats.count, 1)


class SurvivesDedupeTests(unittest.TestCase):
    """Si ce test échoue, les échecs de commandes ne seront plus jamais comptés :
    command_error_release_v41 videra silencieusement ce listener au démarrage."""

    def test_le_listener_d_observabilite_survit_au_nettoyage(self):
        async def on_command_error(ctx, error):
            return None

        async def obsolete_listener(ctx, error):
            return None

        on_command_error.__module__ = "cogs.core_command_observability"
        obsolete_listener.__module__ = "cogs.legacy_errors"

        bot = SimpleNamespace(
            extra_events={"on_command_error": [on_command_error, obsolete_listener]}
        )

        removed = _dedupe_prefix_error_listeners(bot)

        self.assertEqual(removed, 1)
        self.assertEqual(bot.extra_events["on_command_error"], [on_command_error])


if __name__ == "__main__":
    unittest.main()
