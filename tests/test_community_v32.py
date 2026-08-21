import unittest

import discord

from cogs import community_v32


class CommunityV32Tests(unittest.TestCase):
    def test_strip_decorative_emoji(self):
        self.assertEqual(
            community_v32.strip_decorative_emoji("✅ SentriX 🎫 professionnel"),
            "SentriX professionnel",
        )

    def test_simple_embed_text_drops_generic_shell(self):
        embed = discord.Embed(
            title="SentriX / Utilitaires",
            description="Latence : 42 ms",
        )
        self.assertEqual(community_v32.simple_embed_text(embed), "Latence : 42 ms")

    def test_simple_embed_text_keeps_specific_title(self):
        embed = discord.Embed(
            title="Cooldown actif",
            description="Réessaie dans 5 secondes.",
        )
        self.assertEqual(
            community_v32.simple_embed_text(embed),
            "**Cooldown actif**\nRéessaie dans 5 secondes.",
        )

    def test_public_private_exceptions(self):
        self.assertFalse(community_v32._is_public_root("report-bug"))
        self.assertFalse(community_v32._is_public_root("suggest"))


if __name__ == "__main__":
    unittest.main()
