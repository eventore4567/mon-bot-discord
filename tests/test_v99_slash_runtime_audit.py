from __future__ import annotations

import asyncio
import inspect
import unittest

import discord
from discord import app_commands
from discord.ext import commands

import sentrix_v95_runtime as v95
from tools import v99_slash_runtime_audit as v99


class V99SlashRuntimeAuditTests(unittest.TestCase):
    def test_native_setup_exposes_interaction(self):
        async def setup(interaction: discord.Interaction) -> None:
            return None

        command = app_commands.Command(
            name="setup",
            description="Configuration SentriX.",
            callback=setup,
        )
        audit = v99.audit_public_callback(command)

        self.assertTrue(audit.ok, audit.reason)
        self.assertEqual(audit.first_parameter, "interaction")

    def test_legacy_ctx_is_internal_after_v95_adapter(self):
        bot = commands.Bot(command_prefix="+", intents=discord.Intents.none())

        async def legacy(ctx, text: str = "") -> None:
            return None

        legacy_command = commands.Command(legacy, name="ai", description="IA SentriX")
        callback, _native = v95._make_callback(bot, legacy_command)
        public_command = app_commands.Command(
            name="ask",
            description="IA SentriX",
            callback=callback,
        )

        legacy_first = next(iter(inspect.signature(legacy_command.callback).parameters.values()))
        public_audit = v99.audit_public_callback(public_command)

        self.assertEqual(legacy_first.name, "ctx")
        self.assertTrue(public_audit.ok, public_audit.reason)
        self.assertEqual(public_audit.first_parameter, "interaction")

    def test_public_ctx_is_rejected_even_when_annotated_interaction(self):
        async def leaked(ctx: discord.Interaction) -> None:
            return None

        command = app_commands.Command(
            name="leaked-ctx",
            description="Contrôle négatif V99.",
            callback=leaked,
        )
        audit = v99.audit_public_callback(command)

        self.assertFalse(audit.ok)
        self.assertEqual(audit.first_parameter, "ctx")
        self.assertIn("legacy", audit.reason)

    def test_v98_representative_surface_is_clean(self):
        bot, report, targets = v99._build_representative_tree()
        audits = v99.audit_tree(bot.tree)

        self.assertTrue(audits)
        self.assertTrue(all(audit.ok for audit in audits), [audit for audit in audits if not audit.ok])

        setup = next((audit for audit in audits if audit.qualified_name == "setup"), None)
        self.assertIsNotNone(setup)
        self.assertTrue(setup.ok)

        originals = {str(meta.get("original")) for meta in report.values()}
        self.assertTrue(
            {"ai", "ai-translate", "ban", "permission-audit", "ticketpanel"}.issubset(originals)
        )
        self.assertTrue(all(" page-" not in path for path in report))

        for target in targets:
            first = next(iter(inspect.signature(target.command.callback).parameters.values()))
            self.assertEqual(first.name, "ctx")

    def test_adapter_execution_forwards_interaction_to_internal_bridge(self):
        bot = commands.Bot(command_prefix="+", intents=discord.Intents.none())

        async def legacy(ctx, text: str = "") -> None:
            return None

        legacy_command = commands.Command(
            legacy,
            name="ai-translate",
            description="Traduction IA SentriX",
        )
        callback, _native = v95._make_callback(bot, legacy_command)
        marker = object()
        calls = []
        original_invoke = v95._invoke_original

        async def fake_invoke(bot_arg, command_arg, interaction, option_names, kwargs):
            calls.append((bot_arg, command_arg, interaction, option_names, kwargs))

        v95._invoke_original = fake_invoke
        try:
            asyncio.run(callback(marker, text="bonjour"))
        finally:
            v95._invoke_original = original_invoke

        self.assertEqual(len(calls), 1)
        bot_arg, command_arg, interaction, option_names, kwargs = calls[0]
        self.assertIs(bot_arg, bot)
        self.assertIs(command_arg, legacy_command)
        self.assertIs(interaction, marker)
        self.assertEqual(option_names, ("text",))
        self.assertEqual(kwargs, {"text": "bonjour"})


if __name__ == "__main__":
    unittest.main()
