"""Régressions V67 : supprimer seulement les vrais doublons de logs."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "cogs" / "log_consolidation_v61.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _async_function(name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"fonction async {name!r} introuvable")


def _function(name: str) -> ast.FunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"fonction {name!r} introuvable")


class LogRuntimeV67Tests(unittest.TestCase):
    def test_sender_preserves_view_and_event_key_contract(self):
        fn = _async_function("send_consolidated")
        kwonly = {arg.arg for arg in fn.args.kwonlyargs}
        self.assertIn("view", kwonly)
        self.assertIn("event_key", kwonly)

    def test_exact_fingerprint_uses_full_embed_content(self):
        fn = _function("_exact_event_key")
        text = ast.unparse(fn)
        self.assertIn("embed.title", text)
        self.assertIn("embed.description", text)
        self.assertIn("field.name", text)
        self.assertIn("field.value", text)
        self.assertIn("log_type", text)
        self.assertIn("guild.id", text)

    def test_exact_cache_is_bounded_and_ttl_based(self):
        self.assertIn("EXACT_DEDUPE_TTL", SOURCE)
        self.assertIn("EXACT_DEDUPE_MAX", SOURCE)
        self.assertIn("_EXACT_RECENT", SOURCE)
        self.assertIn("_EXACT_INFLIGHT", SOURCE)

    def test_distinct_payloads_are_part_of_the_key(self):
        fn = _function("_exact_event_key")
        text = ast.unparse(fn)
        # Différents membres ou deux renommages différents doivent produire
        # deux clés différentes grâce aux valeurs complètes des champs.
        self.assertIn("field.value", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
