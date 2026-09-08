"""Audit du 2026-09-09 sur les familles tickets/logs/notifications/server/économie/
niveaux/emoji : une trentaine de commandes réelles, sans remplaçant fonctionnel,
étaient masquées de `+help` par le filet générique d'`apply_surface()` — ni fusionnées
dans `/setup` (contrairement à leurs voisines `logsetup`/`create-logs`/`automod-status`),
ni classées nulle part. Un membre ou un staff qui ne connaissait pas déjà le nom exact
d'une de ces commandes n'avait aucun moyen de la découvrir.

Corrigé en les ajoutant à `HELP_VISIBLE_EXTRA_COMMANDS`, sans toucher au budget slash
(aucune n'est ajoutée à `NORMAL_DIRECT_COMMANDS`)."""
from __future__ import annotations

import unittest

from cogs.command_catalog_cleanup import (
    ADMIN_DIRECT_COMMANDS,
    HELP_VISIBLE_EXTRA_COMMANDS,
    NORMAL_DIRECT_COMMANDS,
)


class HelpVisibilityBatchTests(unittest.TestCase):
    def test_commandes_precedemment_orphelines_sont_desormais_listees(self):
        expected = {
            "notifs-ping", "notifs-list", "notifs-remove",
            "logs", "logevent", "logsearch",
            "server-audit", "server-health", "server-growth", "server-managed",
            "economy", "rob", "buy", "sell", "gamble", "deposit", "withdraw",
            "give-money", "reset-economy", "shoppanel", "shoprole", "shop", "weekly",
            "stats", "set-bio", "rep", "reputation", "repleaderboard", "rephistory",
            "voice-time", "level-roles",
            "addemoji", "deleteemoji", "emoji-list",
        }
        missing = expected - HELP_VISIBLE_EXTRA_COMMANDS
        self.assertEqual(missing, set(), f"toujours absentes : {missing}")

    def test_aucune_de_ces_commandes_ne_consomme_le_budget_slash(self):
        """Non-régression : la visibilité +help ne doit jamais entraîner
        l'éligibilité slash (NORMAL_DIRECT_COMMANDS est plafonné à exactement 100,
        déjà saturé — voir tools/command_runtime_audit.py)."""
        overlap = HELP_VISIBLE_EXTRA_COMMANDS & NORMAL_DIRECT_COMMANDS
        self.assertEqual(overlap, set())

    def test_aucun_chevauchement_avec_admin_direct_commands(self):
        """Un nom ne doit apparaître que dans un seul ensemble de visibilité (même
        contrat que tests/test_access_matrix.py::ParityTests pour les permissions)."""
        overlap = HELP_VISIBLE_EXTRA_COMMANDS & ADMIN_DIRECT_COMMANDS
        self.assertEqual(overlap, set())


if __name__ == "__main__":
    unittest.main()
