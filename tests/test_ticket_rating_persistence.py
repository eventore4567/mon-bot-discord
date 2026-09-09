"""Les 5 boutons de notation envoyés en DM après la fermeture d'un ticket
(RatingView) partageaient tous un custom_id fixe ("rate_1".."rate_5", jamais lié à un
ticket précis) et n'étaient jamais réenregistrés via bot.add_view()/add_dynamic_items()
au démarrage. Un redémarrage du bot dans les 24h suivant l'envoi d'une demande de
notation cassait donc définitivement ces boutons pour l'utilisateur qui la recevait.

Corrigé avec le même mécanisme discord.ui.DynamicItem déjà utilisé par /setup
(SetupNavButton) : le custom_id encode maintenant la note ET l'ID du ticket
("ticket_rate:<valeur>:<ticket_id>"), et TicketRatingButton est enregistrée une seule
fois au démarrage (main.py) plutôt que par instance de vue. Test d'exécution réel :
vraie reconstruction via from_custom_id (le mécanisme que Discord utilise réellement
après un redémarrage), vraie base SQLite."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from database.db import Database
from cogs.tickets import RatingView, TicketRatingButton


class TicketRatingPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self._tmpdir.name, "sentrix-test.db"))
        await self.db.connect()

    async def asyncTearDown(self):
        await self.db._conn.close()
        self._tmpdir.cleanup()

    async def _insert_ticket(self) -> int:
        await self.db.execute(
            "INSERT INTO tickets (guild_id, channel_id, user_id, type_id, status, created_at) "
            "VALUES (1, 1, 1, 1, 'ferme', 0)"
        )
        row = await self.db.fetchone("SELECT last_insert_rowid() AS id")
        return row["id"]

    def test_custom_id_encode_bien_la_note_et_le_ticket(self):
        button = TicketRatingButton(4, 999)
        self.assertEqual(button.item.custom_id, "ticket_rate:4:999")

    def test_le_template_matche_le_format_reellement_emis(self):
        template = TicketRatingButton(1, 1).template
        match = template.match("ticket_rate:4:999")
        self.assertIsNotNone(match)
        self.assertEqual(match["value"], "4")
        self.assertEqual(match["ticket_id"], "999")

    async def test_reconstruction_apres_redemarrage_fonctionne_et_ecrit_la_bonne_note(self):
        """C'est exactement le scénario du bug : le bot redémarre, une nouvelle
        instance est reconstruite UNIQUEMENT depuis le custom_id (from_custom_id),
        sans jamais avoir connu le ticket_id/la valeur en mémoire au préalable."""
        ticket_id = await self._insert_ticket()
        custom_id = f"ticket_rate:5:{ticket_id}"
        template = TicketRatingButton(1, 1).template
        match = template.match(custom_id)

        fake_interaction = MagicMock(spec=discord.Interaction)
        fake_button_item = MagicMock(spec=discord.ui.Button)
        reconstructed = await TicketRatingButton.from_custom_id(fake_interaction, fake_button_item, match)

        self.assertEqual(reconstructed.value, 5)
        self.assertEqual(reconstructed.ticket_id, ticket_id)

        fake_interaction.client = MagicMock()
        fake_interaction.client.db = self.db
        fake_interaction.response = MagicMock()
        fake_interaction.response.edit_message = AsyncMock()

        await reconstructed.callback(fake_interaction)

        row = await self.db.fetchone("SELECT rating FROM tickets WHERE id = ?", (ticket_id,))
        self.assertEqual(row["rating"], 5)
        fake_interaction.response.edit_message.assert_awaited_once()

    def test_ratingview_construit_bien_5_boutons_dynamiques(self):
        view = RatingView.__new__(RatingView)
        discord.ui.View.__init__(view, timeout=86400)
        view.cog = MagicMock()
        view.ticket_id = 42
        for i in range(1, 6):
            view.add_item(TicketRatingButton(i, 42))
        custom_ids = sorted(item.item.custom_id for item in view.children)
        self.assertEqual(custom_ids, [f"ticket_rate:{i}:42" for i in range(1, 6)])


if __name__ == "__main__":
    unittest.main()
