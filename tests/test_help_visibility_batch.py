"""Contrat de visibilité des commandes avancées dans +help.

La surface publique a été volontairement réduite : les alias retirés, commandes
fusionnées et actions déjà accessibles sous des groupes slash ne doivent plus être
réaffichés juste pour satisfaire un ancien inventaire. Ce test verrouille uniquement
les commandes avancées qui restent volontairement découvrables en préfixe.
"""
from __future__ import annotations

import unittest

from cogs.command_catalog_cleanup import (
    ADMIN_DIRECT_COMMANDS,
    HELP_VISIBLE_EXTRA_COMMANDS,
    LOW_VALUE_HIDDEN_COMMANDS,
    NORMAL_DIRECT_COMMANDS,
    PURE_DUPLICATE_COMMANDS,
)


class HelpVisibilityBatchTests(unittest.TestCase):
    def test_commandes_avancees_volontairement_visibles_restent_listees(self):
        expected = {
            "ticketsetup", "logsetup",
            "notifs-ping", "notifs-list", "notifs-remove",
            "logevent", "logsearch",
            "rob", "buy", "sell", "gamble", "deposit", "withdraw",
            "rep", "reputation", "repleaderboard",
            "voice-time", "level-roles",
            "addemoji", "deleteemoji", "emoji-list",
        }
        missing = expected - HELP_VISIBLE_EXTRA_COMMANDS
        self.assertEqual(missing, set(), f"toujours absentes : {missing}")
        self.assertNotIn("shop", HELP_VISIBLE_EXTRA_COMMANDS)
        self.assertNotIn("weekly", HELP_VISIBLE_EXTRA_COMMANDS)
        self.assertNotIn("set-bio", HELP_VISIBLE_EXTRA_COMMANDS)
        self.assertNotIn("rephistory", HELP_VISIBLE_EXTRA_COMMANDS)
        self.assertNotIn("economy", HELP_VISIBLE_EXTRA_COMMANDS)
        self.assertNotIn("logs", HELP_VISIBLE_EXTRA_COMMANDS)
        for name in (
            "server-audit", "server-health", "server-growth", "server-managed",
            "give-money", "reset-economy", "shoppanel", "shoprole",
        ):
            self.assertNotIn(name, HELP_VISIBLE_EXTRA_COMMANDS)
        self.assertNotIn("setmodrole", NORMAL_DIRECT_COMMANDS)
        self.assertIn("setmodrole", LOW_VALUE_HIDDEN_COMMANDS)

    def test_aucune_de_ces_commandes_ne_consomme_le_budget_slash(self):
        """Non-régression : ce lot d'orphelines reste +help uniquement.
        +stats a quitté ce lot : c'est désormais la surface profil canonique et une
        commande directe, donc elle est testée avec NORMAL_DIRECT_COMMANDS ailleurs."""
        overlap = HELP_VISIBLE_EXTRA_COMMANDS & NORMAL_DIRECT_COMMANDS
        self.assertEqual(overlap, set())

    def test_les_doublons_confirmes_ne_sont_jamais_visibles(self):
        visible = NORMAL_DIRECT_COMMANDS | HELP_VISIBLE_EXTRA_COMMANDS | ADMIN_DIRECT_COMMANDS
        self.assertEqual(PURE_DUPLICATE_COMMANDS & visible, set())

    def test_aucun_chevauchement_avec_admin_direct_commands(self):
        """Un nom ne doit apparaître que dans un seul ensemble de visibilité (même
        contrat que tests/test_access_matrix.py::ParityTests pour les permissions)."""
        overlap = HELP_VISIBLE_EXTRA_COMMANDS & ADMIN_DIRECT_COMMANDS
        self.assertEqual(overlap, set())


if __name__ == "__main__":
    unittest.main()
