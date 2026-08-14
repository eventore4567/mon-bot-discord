from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cogs" / "stale_discord_app_detector.py"
BOOT = ROOT / "railway_boot.py"
text = SOURCE.read_text(encoding="utf-8")
boot_text = BOOT.read_text(encoding="utf-8")
tree = ast.parse(text, filename=str(SOURCE))


def function(name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Missing function: {name}")


def source(name: str) -> str:
    return ast.get_source_segment(text, function(name)) or ""

fetcher = source("_fetch_guild_integrations")
scan = source("_scan")
health = source("_safe_health")

assert 'Route("GET", "/guilds/{guild_id}/integrations"' in fetcher
assert "manage_guild" in scan, "scanner must only inspect guilds where the bot can manage integrations"
assert "current_application_id" in scan
assert "application_id == current_application_id" in scan
assert "_looks_like_current_brand" in scan
assert "candidate_targets" in scan, "exact cleanup targets may be retained internally"
assert "candidate_count" in health
assert "candidate_apps" in health

# Public health must never reveal server/integration identifiers used for a later cleanup.
for forbidden in ('"guild_id"', '"integration_id"', '"candidate_targets"'):
    assert forbidden not in health, f"public health leaks private cleanup target: {forbidden}"

# Detector phase is read-only. A later cleanup must be a separate, evidence-based patch.
assert 'Route("DELETE"' not in text
assert 'bot.http.request(Route("DELETE"' not in text

assert '"cogs.stale_discord_app_detector" not in bot_main.EXTENSIONS' in boot_text
assert 'bot_main.EXTENSIONS.append("cogs.stale_discord_app_detector")' in boot_text

print("SentriX stale Discord app detector gate: OK (read-only, brand-matched, no guild IDs exposed)")
