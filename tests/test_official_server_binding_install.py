from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMAND_FIX = ROOT / "cogs" / "official_server_command_fix.py"
BINDING_FIX = ROOT / "cogs" / "official_server_binding_fix.py"


def main() -> None:
    command_source = COMMAND_FIX.read_text(encoding="utf-8")
    binding_source = BINDING_FIX.read_text(encoding="utf-8")

    assert "official_server_binding_fix" in command_source
    assert "install_binding_fix(bot)" in command_source
    assert 'MARKER_CHANNELS = ("annonces-sentrix", "règlement")' in binding_source
    assert "_unique_marker_guild" in binding_source
    assert "_sentrix_binding_fix_version = 2" in binding_source
    print("OK: +sentrix-server installs binding V2 with community marker fallback")


if __name__ == "__main__":
    main()
