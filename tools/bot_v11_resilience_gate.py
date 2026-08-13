"""Regression gate for the SentriX Bot V11 runtime hardening."""
from __future__ import annotations

from importlib.machinery import PathFinder
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COGS = ROOT / "cogs"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> None:
    resilience_path = "cogs/bot_resilience_v11.py"
    bridge_path = "cogs/remove_code_command/__init__.py"
    resilience = read(resilience_path)
    bridge = read(bridge_path)
    legacy_bridge = read("cogs/remove_code_command.py")

    compile(resilience, resilience_path, "exec")
    compile(bridge, bridge_path, "exec")

    spec = PathFinder.find_spec("remove_code_command", [str(COGS)])
    assert spec is not None and spec.origin
    assert Path(spec.origin).resolve() == (COGS / "remove_code_command" / "__init__.py").resolve()

    for marker in (
        "install_catalog",
        "install_operations",
        "install_mastery",
        "install_readiness",
        "install_resilience",
        "command.hidden = False",
    ):
        assert marker in bridge, f"V11 bridge missing: {marker}"

    for legacy_marker in (
        "install_command_catalog_cleanup",
        "install_operations_center",
        "install_bot_mastery",
        "install_production_readiness",
    ):
        assert legacy_marker in legacy_bridge, f"Historical loader changed unexpectedly: {legacy_marker}"

    assert "@commands.command" not in resilience
    assert "@commands.hybrid_command" not in resilience
    assert "@app_commands.command" not in resilience

    for marker in (
        "_patch_telemetry",
        "safe_record",
        "_patch_health",
        "safe_health",
        "_prune_state",
        "STALE_COMMAND_SECONDS",
        "COOLDOWN_TTL_SECONDS",
        "COOLDOWN_LIMIT",
        "stuck.intersection_update",
        "_restart_loops",
        "supervisor",
        "on_guild_remove",
    ):
        assert marker in resilience, f"V11 protection missing: {marker}"

    assert "web/" not in resilience
    assert "start_dashboard" not in resilience
    assert "web/" not in bridge
    assert "start_dashboard" not in bridge

    print(
        "OK: V11 loader active; telemetry/health are fail-soft; "
        "runtime caches are bounded; stale command tracking is pruned."
    )


if __name__ == "__main__":
    main()
