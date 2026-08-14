from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cogs" / "slash_reliability_v7.py"
LOADER = ROOT / "cogs" / "__init__.py"
HEALTH = ROOT / "web" / "production_health.py"
RUNTIME_WEB = ROOT / "web" / "dashboard_instance_runtime.py"
ADMIN_GATE = ROOT / "web" / "admin_only_dashboard.py"
text = SOURCE.read_text(encoding="utf-8")
loader_text = LOADER.read_text(encoding="utf-8")
health_text = HEALTH.read_text(encoding="utf-8")
runtime_web_text = RUNTIME_WEB.read_text(encoding="utf-8")
admin_gate_text = ADMIN_GATE.read_text(encoding="utf-8")
tree = ast.parse(text, filename=str(SOURCE))


def function(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Missing function: {name}")


def calls(node: ast.AST, attr: str) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Attribute) and func.attr == attr:
            return True
        if isinstance(func, ast.Name) and func.id == attr:
            return True
    return False


watchdog = function("_defer_watchdog")
settler = function("_settle_deferred")
deferred_detector = function("_interaction_is_deferred")
watchdog_installer = function("_install_watchdog_listener")
completion_installer = function("_install_completion_guard")
relay_installer = function("_install_runtime_relay_loop")
relay_publisher = function("_publish_runtime_relay")
payload_check = function("_original_response_has_payload")
install = function("install")

assert calls(watchdog, "defer"), "slash watchdog must still defer slow interactions"
assert calls(watchdog, "_mark_auto_deferred"), "watchdog defers must be tracked after success"
assert "thinking=True" in (ast.get_source_segment(text, watchdog) or ""), "watchdog must preserve thinking defer semantics"

watchdog_source = ast.get_source_segment(text, watchdog) or ""
assert watchdog_source.index("await interaction.response.defer(thinking=True)") < watchdog_source.index("_mark_auto_deferred(interaction)"), (
    "auto-defer must be marked only after Discord accepts the defer"
)

settler_source = ast.get_source_segment(text, settler) or ""
assert calls(settler, "_take_auto_deferred"), "watchdog tracker must be consumed on completion"
assert calls(settler, "_interaction_is_deferred"), "completion must detect command-owned defer responses"
assert calls(settler, "original_response"), "completion must inspect the original interaction response"
assert calls(settler, "_original_response_has_payload"), "existing command results must be preserved"
assert calls(settler, "edit_original_response"), "empty thinking placeholders must be resolved"
assert "Commande exécutée avec succès." in settler_source
assert "if not tracked_by_watchdog and not _interaction_is_deferred(interaction)" in settler_source, (
    "manual/command-owned defers must be eligible even when the watchdog did not create them"
)
for field in ("last_completion_at", "last_response_type", "last_result", "last_error", "last_command_name"):
    assert field in settler_source, f"live completion telemetry missing: {field}"

manual_defer_source = ast.get_source_segment(text, deferred_detector) or ""
assert "deferred_channel_message" in manual_defer_source
assert "deferred_message_update" in manual_defer_source

payload_source = ast.get_source_segment(text, payload_check) or ""
for field in ("content", "embeds", "attachments", "components", "stickers", "poll"):
    assert field in payload_source, f"payload detector must preserve existing {field}"

watchdog_install_source = ast.get_source_segment(text, watchdog_installer) or ""
assert 'bot.add_listener(watch_interaction, "on_interaction")' in watchdog_install_source, (
    "watchdog must use an event listener instead of replacing tree.interaction_check"
)
assert "tree.interaction_check =" not in watchdog_install_source, (
    "Slash V7 must never assign over the central permission/blacklist interaction check"
)
assert "_sentrix_slash_watchdog_listener_registered" in watchdog_install_source
assert "_schedule_runtime_relay(bot)" in watchdog_install_source, "slash arrival must be relayed across Railway instances"

completion_source = ast.get_source_segment(text, completion_installer) or ""
assert '"on_app_command_completion"' in completion_source, "native slash completion must be covered"
assert '"on_command_completion"' in completion_source, "hybrid slash completion must be covered"
assert "_sentrix_slash_auto_defer_completion_guard" in completion_source
assert "_publish_runtime_relay" in completion_source, "slash completion must be relayed across Railway instances"

relay_source = ast.get_source_segment(text, relay_installer) or ""
assert calls(relay_installer, "create_task"), "cross-instance relay must start as a background runtime loop"
assert "wait_until_ready" in relay_source
assert "_RUNTIME_RELAY_INTERVAL_SECONDS" in relay_source
publisher_source = ast.get_source_segment(text, relay_publisher) or ""
assert "session.post" in publisher_source
assert "_relay_payload" in publisher_source
assert "last_publish_error" in publisher_source

install_source = ast.get_source_segment(text, install) or ""
assert calls(install, "_install_watchdog_listener")
assert calls(install, "_install_completion_guard")
assert calls(install, "_install_runtime_relay_loop")
assert "_sentrix_slash_reliability_v7_installed" in install_source
assert "_rebuild_slash_catalog" not in text, "Slash V7 must not call stale catalog rebuild APIs"
assert "command_catalog_cleanup" not in text, "Slash V7 must not own the command catalog"
assert "command_hybrid_slash_restore_v3" not in text, "Slash V7 must not restore the slash catalog"
assert "slash_command_budget" not in text, "Slash V7 must not mutate slash budgeting"

# Production wiring: the runtime must be imported and actually invoked by the real loader.
assert "from .slash_reliability_v7 import install as install_slash_reliability_v7" in loader_text
assert 'if _matches(name, "cogs.embed_builder")' in loader_text
assert 'await _run_installer("fiabilité slash V7", install_slash_reliability_v7, bot)' in loader_text

# Cross-instance endpoint is installed before the Railway HTTP bind through web.__init__.
assert '_RUNTIME_RELAY_PATH = "/api/runtime/slash-heartbeat"' in runtime_web_text
assert "app.router.add_post(_RUNTIME_RELAY_PATH, _handle_runtime_slash_heartbeat)" in runtime_web_text
assert 'app["slash_runtime_relays"] = {}' in runtime_web_text
for forbidden in ("user_id", "guild_id", "message_content", "token", "prompt"):
    assert f'"{forbidden}"' not in runtime_web_text, f"relay must not expose {forbidden}"

# The global dashboard admin middleware must explicitly allow this machine-to-machine route.
assert '_PUBLIC_RUNTIME_RELAY_PATH = "/api/runtime/slash-heartbeat"' in admin_gate_text
assert "public_runtime_relay = path == _PUBLIC_RUNTIME_RELAY_PATH" in admin_gate_text
assert "or public_runtime_relay" in admin_gate_text, "runtime relay must bypass OAuth/admin session checks"

# Live proof: /health must show local V7 state and all Railway instance relays.
assert '"slash_reliability": _safe_slash_health(bot)' in health_text
assert '"slash_instances": _safe_slash_instances(request.app)' in health_text
for field in (
    '"runtime_installed"',
    '"watchdog_listener_registered"',
    '"completion_guard_registered"',
    '"relay_loop_registered"',
    '"last_interaction_seen_at"',
    '"last_command_name"',
    '"last_completion_at"',
    '"last_result"',
    '"last_publish_error"',
):
    assert field in health_text, f"slash health field missing: {field}"

print("SentriX slash thinking cleanup gate: OK (cross-instance relay public, permissions untouched, defer lifecycle observable)")
