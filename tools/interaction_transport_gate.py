from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cogs" / "interaction_transport_guard.py"
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


enforce = source("_enforce_gateway_transport")
getter = source("_get_current_application")
clearer = source("_clear_interactions_endpoint")
health = source("_safe_health")

assert 'Route("GET", "/applications/@me")' in getter
assert 'Route("PATCH", "/applications/@me")' in clearer
assert '"interactions_endpoint_url": None' in clearer, "HTTP interaction endpoint must be cleared, not replaced"
assert "wait_until_ready" in enforce, "transport must only be changed after Discord login"
assert 'application.get("interactions_endpoint_url")' in enforce
assert "_clear_interactions_endpoint" in enforce
assert "INTERACTIONS_ENDPOINT_STILL_CONFIGURED" in enforce, "clearing must be verified"
assert "bot.tree.sync" in enforce, "slash catalogue must be republished after transport repair"
assert "gateway_confirmed" in enforce
assert "endpoint_was_configured" in health
assert "last_error" in health

# Never expose the previous endpoint URL or bot token through health/logging state.
for forbidden in ('state["endpoint_url"]', '"discord_token"', '"token":', 'config.DISCORD_TOKEN'):
    if forbidden == 'config.DISCORD_TOKEN':
        assert forbidden not in text, "guard must use the authenticated discord.py HTTP client, not read/log the token"
    else:
        assert forbidden not in health

assert '"cogs.interaction_transport_guard" not in bot_main.EXTENSIONS' in boot_text
assert 'bot_main.EXTENSIONS.append("cogs.interaction_transport_guard")' in boot_text

print("SentriX interaction transport gate: OK (Gateway enforced, stale HTTP endpoint cleared, catalogue resynced)")
