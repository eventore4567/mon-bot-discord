"""Non-régression de la vérification renforcée et du honeypot."""
from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cogs" / "security_verification_v3.py"


class SecurityVerificationSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.text)

    def test_module_parses(self):
        self.assertIsInstance(self.tree, ast.Module)

    def test_features_are_off_by_default(self):
        self.assertIn("verification_enabled INTEGER NOT NULL DEFAULT 0", self.text)
        self.assertIn("honeypot_enabled INTEGER NOT NULL DEFAULT 0", self.text)

    def test_honeypot_is_scoped_to_configured_channel(self):
        self.assertIn('message.channel.id != settings["honeypot_channel_id"]', self.text)

    def test_honeypot_exempts_whitelist_and_verified_members(self):
        self.assertIn("await self.is_trusted(message.guild, message.author.id)", self.text)
        self.assertIn("await self.is_verified(message.author, settings)", self.text)
        self.assertIn("core.is_trusted", self.text)

    def test_honeypot_actions_are_bounded(self):
        self.assertIn('_ALLOWED_ACTIONS = {"none", "kick", "softban"}', self.text)
        self.assertNotIn('"ban"}', self.text)

    def test_softban_does_not_delete_message_history(self):
        self.assertIn("delete_message_seconds=0", self.text)
        self.assertIn("await member.guild.unban", self.text)

    def test_verification_checks_screening_age_and_one_time_challenge(self):
        self.assertIn('settings["require_membership_screening"]', self.text)
        self.assertIn("interaction.user.created_at", self.text)
        self.assertIn("security_verification_challenges_v3", self.text)
        self.assertIn("expected_answer", self.text)
        self.assertIn("expires_at", self.text)

    def test_success_assigns_configured_verified_role(self):
        self.assertIn("await member.add_roles(role", self.text)
        self.assertIn("security_verified_members_v3", self.text)

    def test_setup_exposes_security_manager(self):
        self.assertIn('label="Vérification & Honeypot"', self.text)
        self.assertIn('label="Vérification ON / OFF"', self.text)
        self.assertIn('label="Honeypot ON / OFF"', self.text)
        self.assertIn('label="Publier / actualiser les panneaux"', self.text)

    def test_no_progression_table_is_deleted(self):
        forbidden = (
            "DELETE FROM levels", "DELETE FROM economy", "DELETE FROM balances",
            "DELETE FROM user_stats", "DELETE FROM messages_count",
        )
        for marker in forbidden:
            self.assertNotIn(marker, self.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
