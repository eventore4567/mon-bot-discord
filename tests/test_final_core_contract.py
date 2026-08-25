from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class FinalCoreContractTests(unittest.TestCase):
    def test_one_command_transport_owner(self):
        final = text("cogs/final_interaction_policy.py")
        premium_runtime = text("cogs/premium_style_runtime.py")
        response_guard = text("cogs/command_response_guard.py")
        self.assertIn("_sentrix_command_transport_owner", final)
        self.assertIn("commands.Context.send = send", final)
        self.assertIn("commands.Context.reply = reply", final)
        self.assertIn("discord.InteractionResponse.send_message = send_message", final)
        self.assertNotIn("commands.Context.send =", premium_runtime)
        self.assertNotIn("discord.InteractionResponse.send_message =", premium_runtime)
        self.assertNotIn("commands.Context.send =", response_guard)

    def test_one_visual_policy_no_global_monkey_patch(self):
        compat = text("cogs/sentrix_v3_global_style.py")
        ui = text("utils/command_ui_policy.py")
        transport = text("cogs/final_interaction_policy.py")
        self.assertNotIn("premium_style.style_embed =", compat)
        self.assertNotIn("premium_style.style_view =", compat)
        self.assertIn("command_ui_policy.style_kwargs", transport)
        self.assertIn('return "panel"', ui)
        self.assertIn('return "compact"', ui)

    def test_one_error_policy_for_prefix_and_slash(self):
        canonical = text("cogs/command_error_policy.py")
        compat = text("cogs/error_experience_v3.py")
        release = text("cogs/command_error_release_v41.py")
        self.assertIn("bot.on_command_error = on_prefix_error", canonical)
        self.assertIn("bot.tree.on_error = on_slash_error", canonical)
        self.assertIn("_claim_slash_error", canonical)
        self.assertIn("from .command_error_policy", compat)
        self.assertNotIn("bot.tree.on_error = error_with_release", release)

    def test_setup_has_one_renderer_and_language_is_integrated(self):
        setup = text("cogs/setup_oxyde_style.py")
        language_compat = text("cogs/language_setup_finalizer.py")
        self.assertIn("LANGUAGE_PAGE", setup)
        self.assertIn("base_view.render_page = render_page", setup)
        self.assertIn("base_view._sentrix_setup_canonical = True", setup)
        self.assertNotIn("class SetupViewV6", language_compat)
        self.assertNotIn("configuration.SetupView =", language_compat)
        self.assertNotIn("_open_setup_panel", language_compat)

    def test_permission_policy_does_not_grant_structural_power_to_mod_role(self):
        policy = text("cogs/permission_guard.py")
        checks = text("utils/checks.py")
        for permission in ("manage_roles", "manage_channels", "manage_emojis_and_stickers"):
            safe_block = policy.split("SAFE_MOD_ROLE_PERMISSIONS", 1)[1].split("})", 1)[0]
            self.assertNotIn(f'"{permission}"', safe_block)
        self.assertIn("permission not in SAFE_MOD_ROLE_PERMISSIONS", policy)
        self.assertIn("permission not in SAFE_MOD_ROLE_PERMISSIONS", checks)
        self.assertIn("if me is None", checks)

    def test_slash_budget_is_armed_at_import_time(self):
        budget = text("cogs/slash_command_budget.py")
        final_runtime = text("cogs/final_runtime_polish.py")
        self.assertIn("install_class_guard()", budget)
        self.assertIn("slash_command_budget.install_class_guard()", final_runtime)
        self.assertNotIn("command_hybrid_slash_restore_v3", final_runtime)
        self.assertNotIn("SentriXV2", final_runtime)
        self.assertNotIn("SentriXV21", final_runtime)
        self.assertNotIn("SentriXV22", final_runtime)

    def test_no_old_v2_v3_runtime_rewriters_in_finalizer(self):
        final_runtime = text("cogs/final_runtime_polish.py")
        forbidden = (
            "bot_experience_v5", "bot_experience_v6", "sentrix_intelligent_ux",
            "command_centers_v2", "command_direct_aliases_v2",
            "command_hybrid_slash_restore_v3", "command_access_policy_v2",
        )
        for name in forbidden:
            self.assertNotIn(name, final_runtime)

    def test_dashboard_requires_live_administrator_and_csrf(self):
        dashboard = text("web/dashboard.py")
        self.assertIn("member.guild_permissions.administrator", dashboard)
        self.assertIn("_administrator_member(guild, user_id)", dashboard)
        self.assertIn("secrets.compare_digest", dashboard)
        self.assertIn("X-CSRF-Token", dashboard)

    def test_source_files_parse(self):
        paths = (
            "utils/command_ui_policy.py", "cogs/final_interaction_policy.py",
            "cogs/command_error_policy.py", "cogs/permission_guard.py",
            "cogs/setup_oxyde_style.py", "cogs/language_setup_finalizer.py",
            "cogs/slash_command_budget.py", "cogs/final_runtime_polish.py",
        )
        for path in paths:
            ast.parse(text(path), filename=path)


if __name__ == "__main__":
    unittest.main()
