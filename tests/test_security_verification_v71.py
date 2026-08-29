"""Contrats V71 : réglages de sécurité, honeypot et vérification renforcée."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "cogs" / "security_verification_v71.py"
INIT_PATH = ROOT / "cogs" / "__init__.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
INIT = INIT_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _class(name: str) -> ast.ClassDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"classe {name!r} introuvable")


def _async(name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"fonction async {name!r} introuvable")


class SecurityVerificationV71Tests(unittest.TestCase):
    def test_default_threshold_matches_requested_strict_score(self):
        self.assertIn("SCORE_MAX = 2000", SOURCE)
        self.assertIn("DEFAULT_SCORE_THRESHOLD = 1888", SOURCE)
        self.assertIn("verification_threshold INTEGER NOT NULL DEFAULT 1888", SOURCE)

    def test_score_uses_real_discord_signals_not_fake_thousand_factors(self):
        node = next(
            n for n in ast.walk(TREE)
            if isinstance(n, ast.FunctionDef) and n.name == "_score"
        )
        text = ast.unparse(node)
        for signal in (
            "sequence", "code", "math", "screening", "min_age", "join_delay",
            "not_timeout", "role_state", "clean_attempts", "snowflake", "avatar",
        ):
            self.assertIn(signal, text)
        self.assertNotIn("ip_address", SOURCE.casefold())
        self.assertNotIn("device_fingerprint", SOURCE.casefold())

    def test_three_human_challenge_proofs_are_mandatory(self):
        self.assertIn("core_ok", SOURCE)
        self.assertIn("sequence_done", SOURCE)
        self.assertIn("compare_digest", SOURCE)
        self.assertIn("return await original_complete", SOURCE)

    def test_individual_automod_configuration_is_restored(self):
        node = _class("AdvancedAutomodSelect")
        text = ast.unparse(node)
        self.assertIn("setup_ui.AUTOMOD", text)
        self.assertIn("automod_settings", text)
        self.assertIn("security_protections", text)

    def test_raid_intensity_has_real_threshold_profiles(self):
        self.assertIn("RAID_PROFILES", SOURCE)
        self.assertIn('"extreme": (3, 20, 240)', SOURCE)
        node = _async("on_member_join")
        text = ast.unparse(node)
        self.assertIn("antiraid", text)
        self.assertIn("_raid_until", text)
        self.assertIn("add_roles", text)

    def test_honeypot_has_requested_actions_and_delete_first(self):
        for action in ("softban", "kick", "ban", "mute"):
            self.assertIn(f'"{action}"', SOURCE)
        node = _async("on_message")
        text = ast.unparse(node)
        self.assertIn("message.delete", text)
        self.assertIn("guild.ban", text)
        self.assertIn("guild.unban", text)
        self.assertIn("author.kick", text)
        self.assertIn("author.timeout", text)
        self.assertLess(text.index("message.delete"), text.index('action = cfg[\'honeypot_action\']'))

    def test_honeypot_exempts_owner_and_admin(self):
        node = next(
            n for n in ast.walk(TREE)
            if isinstance(n, ast.FunctionDef) and n.name == "_staff_bypass"
        )
        text = ast.unparse(node)
        self.assertIn("guild.owner_id", text)
        self.assertIn("administrator", text)
        self.assertIn("manage_guild", text)
        self.assertIn("verified_role_id", text)

    def test_legacy_honeypot_listener_is_removed_before_v71_listener(self):
        self.assertIn('remove_listener(old_message, "on_message")', SOURCE)
        self.assertIn('bot.add_listener(runtime.on_message, "on_message")', SOURCE)

    def test_setup_has_security_subpages(self):
        self.assertIn('"honeypot"', SOURCE)
        self.assertIn('"verification"', SOURCE)
        self.assertIn("RaidIntensitySelect", SOURCE)
        self.assertIn("VerificationThresholdSelect", SOURCE)
        self.assertIn("HoneypotActionSelect", SOURCE)

    def test_v71_is_final_runtime_layer(self):
        self.assertIn("install_security_verification_v71", INIT)
        self.assertLess(
            INIT.index('await _run_installer("Finition Control Center V70"'),
            INIT.index('await _run_installer("Sécurité avancée et vérification V71"'),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
