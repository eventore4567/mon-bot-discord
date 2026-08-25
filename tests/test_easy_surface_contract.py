from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = (ROOT / "cogs" / "command_catalog_cleanup.py").read_text(encoding="utf-8")
SLASH = (ROOT / "cogs" / "slash_command_budget.py").read_text(encoding="utf-8")
NATURAL = (ROOT / "utils" / "intelligent_ux.py").read_text(encoding="utf-8")


def _quoted_names(block_name: str) -> set[str]:
    match = re.search(
        rf"{re.escape(block_name)}\s*=\s*frozenset\(\{{(?P<body>.*?)\}}\)",
        CATALOG,
        flags=re.S,
    )
    if match is None:
        raise AssertionError(f"Bloc {block_name} introuvable")
    return set(re.findall(r'"([a-z0-9-]+)"', match.group("body")))


class EasySurfaceContractTests(unittest.TestCase):
    def test_easy_surface_stays_small(self):
        roots = _quoted_names("EASY_SLASH_COMMANDS")
        games = _quoted_names("POPULAR_GAME_COMMANDS")
        # EASY_SLASH_COMMANDS est complété par POPULAR_GAME_COMMANDS.
        self.assertLessEqual(len(roots | games), 40)
        self.assertGreaterEqual(len(roots | games), 20)

    def test_only_five_games_are_promoted(self):
        games = _quoted_names("POPULAR_GAME_COMMANDS")
        self.assertEqual(games, {"rps", "guess-number", "trivia", "blackjack", "slots"})
        self.assertIn("GAME_COMMANDS - POPULAR_GAME_COMMANDS", CATALOG)

    def test_advanced_configuration_is_grouped(self):
        easy = _quoted_names("EASY_SLASH_COMMANDS")
        self.assertIn("setup", easy)
        self.assertIn("security", easy)
        self.assertNotIn("setprefix", easy)
        self.assertNotIn("setmodrole", easy)
        self.assertNotIn("antinuke", easy)
        self.assertNotIn("panic", easy)

    def test_old_prefix_functions_are_not_deleted(self):
        self.assertIn("anciennes commandes `+`", CATALOG)
        self.assertNotIn("bot.remove_command", CATALOG)

    def test_slash_guard_rejects_non_product_roots_early(self):
        self.assertIn("if name not in allowed", SLASH)
        self.assertIn("install_class_guard()", SLASH)
        self.assertIn("slash_surface_names", SLASH)

    def test_natural_language_has_zero_memory_entry_points(self):
        self.assertIn('"help", "Ouvrir le menu SentriX"', NATURAL)
        self.assertIn('"setup", "Ouvrir la configuration"', NATURAL)
        self.assertIn('"ping", "Tester SentriX"', NATURAL)
        self.assertIn('"ticket", "Ouvrir les tickets"', NATURAL)


if __name__ == "__main__":
    unittest.main()
