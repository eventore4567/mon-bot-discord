#!/usr/bin/env python3
"""Gate statique V2.2 : aucune nouvelle commande et invariants de polish présents."""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    errors: list[str] = []
    required = (
        "utils/v22_rules.py",
        "cogs/sentrix_v22.py",
        "utils/stats_service.py",
        "web/dashboard_v2_home.py",
        "cogs/final_runtime_polish.py",
        "tests/test_v22_rules.py",
    )
    for relative in required:
        path = ROOT / relative
        if not path.exists():
            errors.append(f"fichier absent: {relative}")
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except Exception as exc:
            errors.append(f"syntaxe invalide {relative}: {exc}")

    runtime = ROOT / "cogs/sentrix_v22.py"
    if runtime.exists():
        text = runtime.read_text(encoding="utf-8")
        forbidden = ("@commands.command", "@commands.hybrid_command", "@commands.group")
        for marker in forbidden:
            if marker in text:
                errors.append(f"V2.2 ajoute une commande alors que c'est interdit: {marker}")
        markers = (
            "last_rob", "_economy_lock", "cash>=?", "status='ouvert' AND claimed_by IS NULL",
            "check_targetable", "asyncio.wait_for", "AI_SETTINGS_TTL", "GAME_SETTINGS_TTL",
            "TICKET_BUTTON_SETTINGS_TTL", "PRAGMA busy_timeout=5000", '"new_commands": 0',
        )
        for marker in markers:
            if marker not in text:
                errors.append(f"invariant V2.2 absent: {marker}")

    stats = ROOT / "utils/stats_service.py"
    if stats.exists():
        text = stats.read_text(encoding="utf-8")
        if "async def _profile_snapshot" not in text:
            errors.append("stats_service: snapshot SQL consolidé absent")
        if "await db.ensure_level" in text or "await db.ensure_economy" in text:
            errors.append("stats_service: une lecture de profil ne doit plus créer de ligne vide")
        if "message_rank_before" not in text:
            errors.append("stats_service: rangs de catégories non regroupés")

    dashboard = ROOT / "web/dashboard_v2_home.py"
    if dashboard.exists():
        text = dashboard.read_text(encoding="utf-8")
        for marker in ("requestAnimationFrame(tick)", "document.hidden", "prefers-reduced-motion", "aria-live"):
            if marker not in text:
                errors.append(f"dashboard V2.2: polish absent: {marker}")

    finalizer = ROOT / "cogs/final_runtime_polish.py"
    if finalizer.exists() and "SentriXV22" not in finalizer.read_text(encoding="utf-8"):
        errors.append("SentriXV22 n'est pas branché au runtime final")

    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC V2.2: {len(errors)} problème(s)")
        return 1
    print("OK V2.2: polish/performance/fiabilité validés, 0 nouvelle commande")
    return 0


if __name__ == "__main__":
    sys.exit(main())
