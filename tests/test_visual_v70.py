from __future__ import annotations

import ast
from pathlib import Path
import unittest

import discord

from utils import embeds


ROOT = Path(__file__).resolve().parents[1]


class VisualV70Tests(unittest.TestCase):
    def test_new_runtime_files_compile(self):
        paths = (
            ROOT / "utils" / "embeds.py",
            ROOT / "cogs" / "sentrix_visual_refactor_v70.py",
            ROOT / "cogs" / "sentrix_profile_refactor_v70.py",
            ROOT / "cogs" / "sentrix_log_safety_v71.py",
            ROOT / "cogs" / "help_catalog_v72.py",
            ROOT / "cogs" / "command_error_release_v41.py",
            ROOT / "cogs" / "user_command_final_v64.py",
        )
        for path in paths:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_banner_is_real_horizontal_asset(self):
        asset = ROOT / "assets" / "sentrix" / "banner-v70.png"
        self.assertTrue(asset.is_file())
        self.assertGreater(asset.stat().st_size, 1000)
        panel = embeds.help_embed("Commandes", "Texte court")
        self.assertEqual(panel.image.url, embeds.SENTRIX_BANNER_URL)
        self.assertIn("banner-v70.png", embeds.SENTRIX_BANNER_URL)

    def test_ui_emoji_cleaner_only_cleans_label(self):
        self.assertEqual(embeds.clean_ui_text("✅ Bannissement réussi"), "Bannissement réussi")
        self.assertEqual(embeds.clean_ui_text("🎫 Tickets"), "Tickets")

        # Les valeurs métier/utilisateur ne passent pas par clean_ui_text.
        source = "raison utilisateur 😈 test"
        panel = embeds.standard("Erreur", source)
        self.assertEqual(panel.description, source)

    def test_one_brand_color_and_footer(self):
        for factory in (
            lambda: embeds.success("ok"),
            lambda: embeds.error("non"),
            lambda: embeds.warning("attention"),
            lambda: embeds.info("info"),
            lambda: embeds.brand("Titre", "texte"),
        ):
            panel = factory()
            self.assertEqual(panel.colour.value, embeds.SENTRIX_COLOR)
            self.assertEqual(panel.footer.text, "SentriX")

    def test_logs_use_standard_embed_fields_and_common_date(self):
        panel = embeds.log_embed(
            "Message modifié",
            fields=(
                ("Auteur", "Tomioka", True),
                ("Salon", "#general", True),
                ("Avant", "ancien texte", False),
                ("Après", "nouveau texte", False),
            ),
        )
        self.assertIsInstance(panel, discord.Embed)
        names = [field.name for field in panel.fields]
        self.assertIn("Auteur", names)
        self.assertIn("Salon", names)
        self.assertIn("Avant", names)
        self.assertIn("Après", names)
        self.assertIn("Date", names)
        self.assertEqual(panel.image.url, embeds.SENTRIX_BANNER_URL)
        self.assertTrue(next(field for field in panel.fields if field.name == "Auteur").inline)
        self.assertFalse(next(field for field in panel.fields if field.name == "Avant").inline)

    def test_log_safety_keeps_primary_guard_and_repair(self):
        source = (ROOT / "cogs" / "sentrix_log_safety_v71.py").read_text(encoding="utf-8")
        self.assertIn("_is_primary_process", source)
        self.assertIn("_repair_log_target", source)
        self.assertIn("_source_key", source)
        self.assertIn("doublon ticket", source)

    def test_help_catalog_includes_prefix_and_slash_subcommands(self):
        source = (ROOT / "cogs" / "help_catalog_v72.py").read_text(encoding="utf-8")
        self.assertIn("bot.walk_commands()", source)
        self.assertIn("for child in getattr(item, \"commands\"", source)
        self.assertIn("slash-only", source)

    def test_obsolete_plain_help_and_components_log_layers_removed(self):
        self.assertFalse((ROOT / "cogs" / "help_plain_compact_v65.py").exists())
        self.assertFalse((ROOT / "cogs" / "log_fixed_compact_v56.py").exists())


if __name__ == "__main__":
    unittest.main()
