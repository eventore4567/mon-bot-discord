from __future__ import annotations

import unittest

import discord

from cogs import community_v33


class _User:
    id = 123456789


class _Bot:
    user = _User()


class CommunityV33Tests(unittest.TestCase):
    def test_personal_slash_commands_are_private(self):
        for name in ("profile", "balance", "inventory", "ai", "help", "stats", "ticket"):
            self.assertIn(name, community_v33.PRIVATE_SLASH_ROOTS)

    def test_simple_embed_becomes_native_text(self):
        embed = discord.Embed(title="Information", description="Réponse simple")
        self.assertEqual(
            community_v33._simple_embed_to_text(embed, has_view=False),
            "Réponse simple",
        )

    def test_rich_embed_stays_rich(self):
        embed = discord.Embed(title="Profil", description="Données")
        embed.add_field(name="Niveau", value="10")
        self.assertIsNone(community_v33._simple_embed_to_text(embed, has_view=False))

    def test_log_channel_name_normalisation_handles_decorations(self):
        self.assertEqual(
            community_v33._normalise_name("💬・logs-messages"),
            "logs-messages",
        )

    def test_bot_authored_message_log_is_detected(self):
        embed = discord.Embed(title="Message modifié")
        embed.add_field(name="Auteur", value="<@123456789>\n`123456789`")
        self.assertTrue(community_v33._embed_mentions_bot_author(_Bot(), embed))

    def test_source_channel_is_extracted_from_log_embed(self):
        embed = discord.Embed(title="Message modifié")
        embed.add_field(name="Salon", value="<#987654321>")
        self.assertEqual(community_v33._embed_source_channel_id(embed), 987654321)

    def test_ai_commands_have_relaxed_latency_alert_policy(self):
        self.assertIn("ai", community_v33.AI_COMMAND_ROOTS)
        self.assertIn("sentrix", community_v33.AI_COMMAND_ROOTS)


if __name__ == "__main__":
    unittest.main()
