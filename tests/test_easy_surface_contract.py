from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = (ROOT / "cogs" / "command_catalog_cleanup.py").read_text(encoding="utf-8")
SLASH = (ROOT / "cogs" / "slash_command_budget.py").read_text(encoding="utf-8")
NATURAL = (ROOT / "utils" / "intelligent_ux.py").read_text(encoding="utf-8")
FINAL = (ROOT / "cogs" / "final_runtime_polish.py").read_text(encoding="utf-8")
HELP = (ROOT / "cogs" / "help_simple.py").read_text(encoding="utf-8")


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
    def test_slash_surface_keeps_the_old_useful_catalogue(self):
        direct = _quoted_names("SLASH_COMMANDS")
        games = _quoted_names("GAME_COMMANDS")
        total = direct | games
        self.assertLessEqual(len(total), 100)
        self.assertGreaterEqual(len(total), 90)
        self.assertEqual(len(total), 100)

    def test_all_historical_games_remain_available_in_slash_budget(self):
        games = _quoted_names("GAME_COMMANDS")
        self.assertGreaterEqual(len(games), 40)
        for name in ("rps", "guess-number", "trivia", "blackjack", "slots", "tictactoe", "connect4"):
            self.assertIn(name, games)

    def test_only_real_duplicates_or_centres_free_slash_slots(self):
        direct = _quoted_names("SLASH_COMMANDS")
        for removed in ("setprefix", "setmodrole", "antinuke", "panic", "blacklist-add", "leaderboard-money", "giveaway-reroll"):
            self.assertNotIn(removed, direct)
        for centre in ("setup", "security", "ticket", "giveaway"):
            self.assertIn(centre, direct)

    def test_freed_slots_promote_useful_prefix_commands(self):
        direct = _quoted_names("SLASH_COMMANDS")
        for promoted in ("info", "membercount", "poll", "remind", "translate", "weather", "profile", "shop", "deposit", "gamble"):
            self.assertIn(promoted, direct)

    def test_old_prefix_functions_are_not_deleted(self):
        self.assertIn("anciennes commandes `+`", CATALOG)
        self.assertNotIn("bot.remove_command", CATALOG)
        self.assertIn("HELP_HIDDEN_COMMANDS", CATALOG)

    def test_slash_guard_is_early_and_respects_discord_limit(self):
        self.assertIn("GLOBAL_CHAT_INPUT_BUDGET = 100", SLASH)
        self.assertIn("if name not in allowed", SLASH)
        self.assertIn("install_class_guard()", SLASH)
        self.assertIn("slash_surface_names", SLASH)

    def test_help_has_one_simple_owner(self):
        self.assertIn("help_simple.install(bot)", FINAL)
        self.assertIn('bot._sentrix_help_owner = "cogs.help_simple"', FINAL)
        self.assertIn('title = "Aide"', HELP)
        self.assertIn("Choisis une catégorie ou utilise Rechercher", HELP)
        self.assertNotIn("emoji=", HELP)

    def test_natural_language_has_zero_memory_entry_points(self):
        self.assertIn('"help", "Ouvrir le menu SentriX"', NATURAL)
        self.assertIn('"setup", "Ouvrir la configuration"', NATURAL)
        self.assertIn('"ping", "Tester SentriX"', NATURAL)
        self.assertIn('"ticket", "Ouvrir les tickets"', NATURAL)


if __name__ == "__main__":
    unittest.main()
