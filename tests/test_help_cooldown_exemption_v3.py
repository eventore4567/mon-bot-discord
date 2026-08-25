from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXEMPTION = ROOT / "cogs" / "help_cooldown_exemption_v3.py"
INSTALLER = ROOT / "cogs" / "command_no_emoji_runtime.py"


class HelpCooldownExemptionV3Tests(unittest.TestCase):
    def test_help_is_the_exempt_root(self):
        tree = ast.parse(EXEMPTION.read_text(encoding="utf-8"))
        values = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "_HELP_ROOTS":
                        call = node.value
                        self.assertIsInstance(call, ast.Call)
                        container = call.args[0]
                        self.assertIsInstance(container, (ast.Set, ast.List, ast.Tuple))
                        values.update(
                            element.value
                            for element in container.elts
                            if isinstance(element, ast.Constant) and isinstance(element.value, str)
                        )
        self.assertEqual(values, {"help"})

    def test_both_cooldown_layers_are_patched(self):
        source = EXEMPTION.read_text(encoding="utf-8")
        self.assertIn("_patch_global_prefix_cooldown(bot)", source)
        self.assertIn("_patch_v41_guards()", source)
        self.assertIn("hardening._duplicate_retry = duplicate_retry", source)
        self.assertIn("hardening._slash_rate_retry = slash_rate_retry", source)
        self.assertIn("hardening._acquire = acquire", source)

    def test_runtime_installs_the_exemption(self):
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("help_cooldown_exemption_v3", source)
        self.assertIn("install_help_cooldown_exemption_v3(bot)", source)


if __name__ == "__main__":
    unittest.main()
