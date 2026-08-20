#!/usr/bin/env python3
"""Gate statique V2.1 : intégration, sécurité de portée et dette legacy visible."""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

REQUIRED = (
    "utils/v21_rules.py",
    "cogs/sentrix_v21.py",
    "web/dashboard_v21.py",
    "cogs/sentrix_v2.py",
    "cogs/premium_style_runtime.py",
    "cogs/production_observability_v9.py",
    "web/production_health.py",
)


def parse(path: pathlib.Path, errors: list[str]):
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception as exc:
        errors.append(f"{path.relative_to(ROOT)}: syntaxe invalide: {exc}")
        return None


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    for relative in REQUIRED:
        path = ROOT / relative
        if not path.exists():
            errors.append(f"fichier requis absent: {relative}")
            continue
        parse(path, errors)

    v21_path = ROOT / "cogs/sentrix_v21.py"
    if v21_path.exists():
        text = v21_path.read_text(encoding="utf-8")
        required_markers = (
            "market-find",
            "market-history",
            "market-my",
            "achievements",
            "challenges",
            "systemstatus",
            "guild_id=?",
            "status='processing'",
            "Remboursement marché V2.1",
            "sell.params = sell_params",
            "buy.params = buy_params",
        )
        for marker in required_markers:
            if marker not in text:
                errors.append(f"sentrix_v21.py: invariant absent: {marker}")

    dashboard_path = ROOT / "web/dashboard_v21.py"
    if dashboard_path.exists():
        text = dashboard_path.read_text(encoding="utf-8")
        for marker in ('fetch("/health"', "@media(max-width:680px)", 'credentials:"same-origin"'):
            if marker not in text:
                errors.append(f"dashboard_v21.py: invariant absent: {marker}")
        if "DISCORD_TOKEN" in text or "OPENAI_API_KEY" in text:
            errors.append("dashboard_v21.py: un nom de secret ne doit pas être injecté côté navigateur")

    premium = ROOT / "cogs/premium_style_runtime.py"
    if premium.exists():
        text = premium.read_text(encoding="utf-8")
        for marker in ("_patch_context_send", "_patch_interaction_response", "_patch_webhook_followups", "_patch_design_system"):
            if marker not in text:
                errors.append(f"style global incomplet: {marker} absent")

    observability = ROOT / "cogs/production_observability_v9.py"
    if observability.exists():
        text = observability.read_text(encoding="utf-8")
        for marker in ("production_command_metrics", "production_health_snapshots", "stuck_watchdog", "build_health_snapshot"):
            if marker not in text:
                errors.append(f"observabilité incomplète: {marker} absent")

    # Les doublons racine historiques sont signalés mais jamais supprimés automatiquement :
    # certains déploiements externes peuvent encore les importer directement.
    pairs = (
        ("db.py", "database/db.py"),
        ("minigames.py", "cogs/minigames.py"),
        ("games_setup.py", "cogs/games_setup.py"),
    )
    for legacy, canonical in pairs:
        if (ROOT / legacy).exists() and (ROOT / canonical).exists():
            warnings.append(f"dette legacy à vérifier avant suppression: {legacy} ↔ {canonical}")

    for warning in warnings:
        print(f"[WARN] {warning}")
    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC V2.1: {len(errors)} problème(s)")
        return 1
    print(f"OK V2.1: intégration/style/monitoring/marché validés ({len(warnings)} avertissement(s) legacy)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
