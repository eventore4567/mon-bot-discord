from __future__ import annotations

from pathlib import Path
import unittest

import discord

from cogs import final_interaction_policy as policy

ROOT = Path(__file__).resolve().parents[1]


class RuntimeResponseTransportTests(unittest.TestCase):
    def test_long_text_is_paginated_without_truncation(self):
        markers = [f"segment-{index:03d}-" + ("x" * 160) for index in range(80)]
        text = "\n".join(markers)

        pages = policy._payload_pages((text,), {}, root="help")

        self.assertGreater(len(pages), 1)
        rendered = []
        for args, kwargs in pages:
            self.assertFalse(kwargs.get("embeds"), "une page longue ne doit pas regrouper de gros embeds")
            embed = kwargs.get("embed")
            self.assertIsInstance(embed, discord.Embed)
            self.assertLessEqual(len(embed), 3900)
            rendered.append(str(embed.description or ""))
            if args:
                self.assertIsNone(args[0])
        joined = "\n".join(rendered)
        self.assertNotIn("Réponse tronquée", joined)
        self.assertIn(markers[0], joined)
        self.assertIn(markers[-1], joined)

    def test_short_text_stays_one_embed_message(self):
        pages = policy._payload_pages(("Commande terminée.",), {}, root="test")
        self.assertEqual(len(pages), 1)
        args, kwargs = pages[0]
        self.assertIsNone(args[0])
        self.assertIsInstance(kwargs.get("embed"), discord.Embed)
        self.assertNotIn("embeds", kwargs)

    def test_explicit_ping_keeps_only_ping_in_content(self):
        role = "<@&1355855757991481476>"
        pages = policy._payload_pages(
            (f"{role} Nouvelle information importante.",),
            {"allowed_mentions": discord.AllowedMentions(roles=True)},
            root="notify",
        )
        self.assertEqual(len(pages), 1)
        args, kwargs = pages[0]
        self.assertEqual(args[0], role)
        self.assertIsInstance(kwargs.get("embed"), discord.Embed)
        self.assertIn("Nouvelle information importante.", str(kwargs["embed"].description))

    def test_late_invariant_no_longer_rewraps_all_discord_transports(self):
        source = (ROOT / "cogs" / "command_embed_invariant.py").read_text(encoding="utf-8")
        self.assertNotIn("commands.Context.send =", source)
        self.assertNotIn("discord.abc.Messageable.send =", source)
        self.assertNotIn("discord.InteractionResponse.send_message =", source)
        self.assertNotIn("discord.Webhook.send =", source)
        self.assertIn("final_interaction_policy", source)

    def test_setup_acknowledges_before_building_heavy_embed(self):
        source = (ROOT / "cogs" / "control_center_v3_ui_fix.py").read_text(encoding="utf-8")
        refresh_start = source.index("async def refresh(self, interaction: discord.Interaction):")
        refresh_end = source.index("refresh._sentrix_setup_safe_refresh", refresh_start)
        refresh = source[refresh_start:refresh_end]
        self.assertLess(
            refresh.index("await _ack_interaction(interaction)"),
            refresh.index("embed = await self.build_embed()"),
        )
        self.assertIn("interaction.edit_original_response", refresh)

    def test_final_error_owner_replaces_existing_prefix_response(self):
        source = (ROOT / "cogs" / "final_error_embed_v5.py").read_text(encoding="utf-8")
        self.assertIn('getattr(ctx, "_sentrix_response_sent", False)', source)
        self.assertIn("await _replace_prefix_response(ctx, panel)", source)
        self.assertIn("await raw_edit(interaction, content=None, embeds=[], view=panneau", source)


if __name__ == "__main__":
    unittest.main()
