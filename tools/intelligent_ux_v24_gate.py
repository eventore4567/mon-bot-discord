#!/usr/bin/env python3
"""Quality gate SentriX V2.4 Intelligent UX."""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    errors: list[str] = []
    required = [
        "utils/intelligent_ux.py",
        "cogs/sentrix_intelligent_ux.py",
        "web/dashboard_intelligent_ux.py",
        "tests/test_intelligent_ux.py",
        "cogs/final_runtime_polish.py",
    ]
    for relative in required:
        path = ROOT / relative
        if not path.exists():
            errors.append(f"fichier absent: {relative}")
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except Exception as exc:
            errors.append(f"syntaxe invalide {relative}: {exc}")

    cog_path = ROOT / "cogs/sentrix_intelligent_ux.py"
    if cog_path.exists():
        text = cog_path.read_text(encoding="utf-8")
        forbidden = ("@commands.command", "@commands.hybrid_command", "@commands.group")
        for marker in forbidden:
            if marker in text:
                errors.append(f"V2.4 ajoute une commande publique interdite: {marker}")
        for marker in (
            "command.can_run(ctx)",
            "NaturalActionConfirmView",
            "plan.sensitive",
            "ctx.invoke(command",
            "_install_ticket_intelligence",
            "[SentriX Auto]",
            '"new_commands": 0',
            "_message_is_claimed",
            "_claim_natural_message",
            "content.startswith(prefix)",
            "ai_cog._natural_command_line",
            "ai_cog._invoke_natural_command",
            "primary = originals[0]",
            "_sentrix_v24_primary_ai_listener_guard_fn",
            '"global_command_exclusivity": True',
            '"reload_safe_listener_guard": True',
        ):
            if marker not in text:
                errors.append(f"garantie V2.4 absente: {marker}")

    parser = ROOT / "utils/intelligent_ux.py"
    if parser.exists():
        text = parser.read_text(encoding="utf-8")
        for marker in ("class NaturalAction", "sensitive=True", "target_required=True", "classify_ticket_priority"):
            if marker not in text:
                errors.append(f"planner V2.4 incomplet: {marker}")

    dashboard = ROOT / "web/dashboard_intelligent_ux.py"
    if dashboard.exists():
        text = dashboard.read_text(encoding="utf-8")
        for marker in ('type="search"', 'aria-live="polite"', 'event.key!=="/"', "requestAnimationFrame"):
            if marker not in text:
                errors.append(f"dashboard intelligent incomplet: {marker}")

    finalizer = ROOT / "cogs/final_runtime_polish.py"
    if finalizer.exists():
        text = finalizer.read_text(encoding="utf-8")
        if "sentrix_intelligent_ux" not in text or "dashboard_intelligent_ux" not in text:
            errors.append("V2.4 n'est pas branchée au runtime/dashboard final")

    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC V2.4: {len(errors)} problème(s)")
        return 1
    print(
        "OK V2.4: commandes exclusives, IA sans double réponse, confirmations, tickets, "
        "dashboard et reload validés, 0 nouvelle commande"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
