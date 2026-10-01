from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_help_uses_short_prefix_name_as_primary_display():
    source = (ROOT / "cogs" / "help.py").read_text(encoding="utf-8")

    assert "def _display_name(command: commands.Command)" in source
    assert 'label = f"{prefix}{_display_name(command)}"' in source
    assert 'name = _display_name(command)' in source
    assert 'titre=f"SentriX — {_display_name(exact)}"' in source


def test_help_keeps_long_command_name_as_alternate():
    source = (ROOT / "cogs" / "help.py").read_text(encoding="utf-8")

    assert "if short_name != command.qualified_name:" in source
    assert "alias.append(command.qualified_name)" in source
    assert '"Autres noms"' in source


def test_help_examples_prefer_short_name_without_breaking_long_name():
    source = (ROOT / "cogs" / "help.py").read_text(encoding="utf-8")

    assert "def _example(command: commands.Command, prefix: str)" in source
    assert 'long_call = f"{prefix}{command.qualified_name}"' in source
    assert 'short_call = f"{prefix}{_display_name(command)}"' in source
