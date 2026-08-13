"""Regression gate for Bot V11 custom-command resilience."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "cogs" / "custom_command_failsafe_v11.py"
LOADER = ROOT / "cogs" / "remove_code_command" / "__init__.py"


def main() -> None:
    source = PATCH.read_text(encoding="utf-8")
    loader = LOADER.read_text(encoding="utf-8")
    compile(source, str(PATCH), "exec")
    compile(loader, str(LOADER), "exec")

    required = (
        "_sentrix_custom_commands_v10",
        "_sentrix_custom_commands_usage_failsafe_v11",
        "v10_custom_command_usage",
        "except Exception:",
        "return await _original(message)",
        "_custom_cooldowns",
        "repair_loop",
    )
    for marker in required:
        assert marker in source, f"missing custom-command safety marker: {marker}"

    assert "install_custom_command_failsafe" in loader
    assert "await install_custom_command_failsafe(bot)" in loader
    assert "@commands.command" not in source
    assert "@commands.hybrid_command" not in source
    assert "start_dashboard" not in source
    assert "web/" not in source

    metric_write = source.index("v10_custom_command_usage")
    metric_guard = source.index("except Exception:", metric_write)
    original_call = source.index("return await _original(message)", metric_guard)
    assert metric_write < metric_guard < original_call

    print("OK: custom-command usage metrics are fail-soft and the V11 loader installs the patch.")


if __name__ == "__main__":
    main()
