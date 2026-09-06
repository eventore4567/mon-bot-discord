from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUDGET = ROOT / "cogs" / "slash_command_budget.py"
CATALOG = ROOT / "cogs" / "command_catalog_cleanup.py"


def test_ticket_slash_group_source_compiles():
    source = BUDGET.read_text(encoding="utf-8")
    ast.parse(source, filename=str(BUDGET))


def test_ticket_is_one_slash_root_with_expected_actions():
    source = BUDGET.read_text(encoding="utf-8")
    assert 'app_commands.Group(\n        name="ticket"' in source
    for name in (
        "open",
        "close",
        "reopen",
        "claim",
        "unclaim",
        "add",
        "remove",
        "rename",
        "transcript",
        "setup",
    ):
        assert f'@group.command(name="{name}"' in source
    assert "tree.add_command(group, override=True)" in source


def test_ticket_controls_reuse_runtime_security_instead_of_duplicating_it():
    source = BUDGET.read_text(encoding="utf-8")
    assert "await cog.handle_control_button(interaction, key)" in source
    assert "from .ticket_claim_security import _authorized_staff" in source
    assert "await cog.generate_transcript(interaction.channel)" in source


def test_old_ticket_roots_stay_merged_not_global_slash_roots():
    source = CATALOG.read_text(encoding="utf-8")
    block = source.split("TICKET_MERGED_COMMANDS = frozenset({", 1)[1].split("})", 1)[0]
    for old_root in (
        "ticketsetup",
        "ticketpanel",
        "ticketconfig",
        "ticketlogs",
        "ticketlimit",
        "ticketautoclose",
        "ticket-reopen",
        "tickettranscript",
        "ticketstats",
    ):
        assert f'"{old_root}"' in block


def test_prefix_ticket_commands_are_not_removed_by_group_installer():
    source = BUDGET.read_text(encoding="utf-8")
    installer = source.split("def _install_ticket_group", 1)[1].split("def finalize", 1)[0]
    assert "bot.remove_command" not in installer
    assert "Les commandes préfixées (+ticket" in installer
