"""Les boutons "Copier l'ID" des logs (RevealIdButton, utils/log_service.py) avaient
déjà un custom_id auto-suffisant ("sxid:<id>") et `timeout=None`, mais n'étaient
jamais réenregistrés via `bot.add_view()`/`add_dynamic_items()` au démarrage. Tout log
envoyé avant le redémarrage le plus récent (fréquent sur Railway) gardait ses boutons
visibles, mais cliquer dessus échouait silencieusement côté Discord.

Corrigé avec le même mécanisme discord.ui.DynamicItem déjà utilisé par /setup
(SetupNavButton) et la notation de tickets (TicketRatingButton). Test d'exécution
réel : vraie reconstruction via from_custom_id, comme Discord le fait après un
redémarrage."""
from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from utils.log_service import RevealIdButton


class LogRevealIdPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def test_custom_id_encode_bien_l_id(self):
        button = RevealIdButton("Copier l'ID du membre", 123456789)
        self.assertEqual(button.item.custom_id, "sxid:123456789")

    async def test_reconstruction_apres_redemarrage_fonctionne(self):
        """C'est exactement le scénario du bug : le bot redémarre, une nouvelle
        instance est reconstruite UNIQUEMENT depuis le custom_id (from_custom_id),
        sans jamais avoir connu l'ID à l'avance."""
        template = RevealIdButton("x", 1).template
        match = template.match("sxid:987654321")
        self.assertIsNotNone(match)

        fake_item = MagicMock(spec=discord.ui.Button)
        fake_item.label = "Copier l'ID du membre"
        reconstructed = await RevealIdButton.from_custom_id(MagicMock(), fake_item, match)

        self.assertEqual(reconstructed.entity_id, 987654321)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()
        await reconstructed.callback(interaction)

        interaction.response.send_message.assert_awaited_once()
        args, kwargs = interaction.response.send_message.call_args
        self.assertIn("987654321", args[0])
        self.assertTrue(kwargs.get("ephemeral"))


if __name__ == "__main__":
    unittest.main()
