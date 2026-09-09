"""`+ticketsetup` (le hub de configuration complet des tickets : plusieurs panels,
plusieurs types, formulaires, logs...) était masqué de `+help` comme tout le reste de
TICKET_MERGED_COMMANDS. Mais contrairement aux autres commandes "fusionnées", rien ne
le remplace : `/setup` (setup_ticket_autoconfig_v72.py) ne fait qu'auto-créer UN panel
"Support" par défaut. Un serveur voulant plusieurs types de tickets (Achat,
Partenariat, Signalement...) n'avait donc AUCUN chemin découvrable pour y arriver —
seuls des utilisateurs qui connaissaient déjà le nom exact de la commande pouvaient
la taper.

Corrigé en rendant uniquement la porte d'entrée (+ticketsetup) visible, sans toucher
au budget slash (elle reste explicitement exclue de la resynchronisation slash, comme
avant) ni aux sous-commandes qu'elle ouvre (ticketpanel, tickettype... restent
masquées, atteignables via les boutons du hub)."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
from discord.ext import commands

from cogs import command_catalog_cleanup


class TicketSetupHelpVisibilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        intents = discord.Intents.none()
        self.bot = commands.Bot(command_prefix="+", intents=intents)
        import cogs.tickets as tickets_module
        await tickets_module.setup(self.bot)

    async def test_ticketsetup_est_visible_dans_plus_help(self):
        """C'est exactement le bug rapporté : avant le correctif, ce test échoue
        (hidden=True) — un admin ne pouvait pas découvrir comment créer plusieurs
        types de tickets."""
        command_catalog_cleanup.apply_surface(self.bot)
        ticketsetup = self.bot.get_command("ticketsetup")
        self.assertIsNotNone(ticketsetup)
        self.assertFalse(ticketsetup.hidden)

    async def test_les_sous_commandes_du_hub_restent_masquees(self):
        """Non-régression : seule la porte d'entrée devient visible, pas tout
        TICKET_MERGED_COMMANDS (le reste s'atteint via les boutons du hub)."""
        command_catalog_cleanup.apply_surface(self.bot)
        for name in ("ticketpanel", "tickettype", "ticketform", "ticketconfig"):
            with self.subTest(name=name):
                command = self.bot.get_command(name)
                if command is not None:
                    self.assertTrue(command.hidden)

    def test_ticketsetup_reste_exclue_du_budget_slash(self):
        """Non-régression : rendre +ticketsetup visible dans +help ne doit pas la
        faire entrer en compétition pour une des 100 racines slash déjà saturées."""
        self.assertIn("ticketsetup", command_catalog_cleanup.MERGED_COMMANDS)


if __name__ == "__main__":
    unittest.main()
