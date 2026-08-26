from __future__ import annotations

import ast
from pathlib import Path
import unittest

import discord

from cogs import command_embed_invariant as invariant

ROOT = Path(__file__).resolve().parents[1]


class CommandEmbedInvariantTests(unittest.TestCase):
    def test_source_compiles_and_is_loaded_by_last_railway_guard(self):
        path = ROOT / "cogs" / "command_embed_invariant.py"
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        guard = (ROOT / "cogs" / "slash_error_completion_guard.py").read_text(encoding="utf-8")
        self.assertIn("from . import command_embed_invariant", guard)
        self.assertIn("command_embed_invariant.install(bot)", guard)

    def test_plain_command_text_becomes_embed(self):
        args, kwargs = invariant._normalize_command_payload(
            ("Commande terminée.",),
            {},
            root="test",
        )
        self.assertIsNone(args[0])
        self.assertIsInstance(kwargs.get("embed"), discord.Embed)
        self.assertIn("Commande terminée.", str(kwargs["embed"].description))

    def test_keyword_content_becomes_embed(self):
        args, kwargs = invariant._normalize_command_payload(
            (),
            {"content": "Une information importante."},
            root="test",
        )
        self.assertEqual(args, ())
        self.assertIsNone(kwargs.get("content"))
        self.assertIsInstance(kwargs.get("embed"), discord.Embed)
        self.assertIn("Une information importante.", str(kwargs["embed"].description))

    def test_real_ping_keeps_only_mention_outside_embed(self):
        role = "<@&1355855757991481476>"
        text = f"{role} Une nouvelle annonce est disponible."
        allowed = discord.AllowedMentions(roles=True)
        args, kwargs = invariant._normalize_command_payload(
            (text,),
            {"allowed_mentions": allowed},
            root="notify",
        )
        self.assertEqual(args[0], role)
        self.assertIs(kwargs.get("allowed_mentions"), allowed)
        self.assertIsInstance(kwargs.get("embed"), discord.Embed)
        self.assertIn("Une nouvelle annonce est disponible.", str(kwargs["embed"].description))

    def test_content_plus_existing_embed_has_no_plain_text(self):
        existing = discord.Embed(title="Résultat", description="Détail métier")
        args, kwargs = invariant._normalize_command_payload(
            (),
            {"content": "Texte historique hors embed", "embed": existing},
            root="test",
        )
        self.assertEqual(args, ())
        self.assertIsNone(kwargs.get("content"))
        self.assertNotIn("embed", kwargs)
        self.assertGreaterEqual(len(kwargs.get("embeds", [])), 2)
        rendered = "\n".join(str(item.description or "") for item in kwargs["embeds"])
        self.assertIn("Texte historique hors embed", rendered)
        self.assertIn("Détail métier", rendered)

    def test_ping_plus_existing_embed_keeps_only_mention_in_content(self):
        role = "<@&1355855757991481476>"
        existing = discord.Embed(title="Annonce", description="Détail")
        allowed = discord.AllowedMentions(roles=True)
        args, kwargs = invariant._normalize_command_payload(
            (),
            {
                "content": f"{role} Nouvelle information importante.",
                "embed": existing,
                "allowed_mentions": allowed,
            },
            root="notify",
        )
        self.assertEqual(args, ())
        self.assertEqual(kwargs.get("content"), role)
        self.assertNotIn("embed", kwargs)
        self.assertGreaterEqual(len(kwargs.get("embeds", [])), 2)
        rendered = "\n".join(str(item.description or "") for item in kwargs["embeds"])
        self.assertIn("Nouvelle information importante.", rendered)

    def test_ping_stub_deduplicates_mentions(self):
        member = "<@1355855757991481475>"
        role = "<@&1355855757991481476>"
        self.assertEqual(
            invariant._ping_stub(f"{member} hello {member} {role} world"),
            f"{member} {role}",
        )


if __name__ == "__main__":
    unittest.main()
