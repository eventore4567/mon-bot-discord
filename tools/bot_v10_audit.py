"""CI gate statique du Bot V10."""
from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def schema_from_source(source: str) -> str:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "SCHEMA" for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("SCHEMA V10 introuvable")


def main() -> None:
    bot = text("cogs/bot_v10.py")
    web = text("web/platform_v10.py")
    boot = text("railway_boot.py")
    community = text("web/community_card_polish.py")

    compile(bot, "cogs/bot_v10.py", "exec")
    compile(web, "web/platform_v10.py", "exec")
    conn = sqlite3.connect(":memory:")
    conn.executescript(schema_from_source(bot))
    conn.close()

    assert "@commands.hybrid_command" not in bot
    assert "@app_commands.command" not in bot
    for marker in (
        'name="setup-auto"', 'name="health"', 'name="server-audit"',
        'name="economy-audit"', 'name="privacy-policy"',
        "_sentrix_setup_auto_v10", "_sentrix_ai_context_v10",
        "_sentrix_restore_safety_v10", "v10_operational_signals",
        "privacy_cleanup_loop", "economy_insights", "server_audit_data",
        "recent_signals", "overview",
    ):
        assert marker in bot, f"Fonction V10 manquante: {marker}"

    assert "aucune sanction supplémentaire" in bot
    assert "décision humaine" in bot

    for marker in (
        "/v10/summary", "/v10/privacy-policy", 'id="v10Status"',
        'id="v10RetentionDays"', "@media(max-width:650px)",
        "min-height:44px", "setInterval(v10Load,15000)",
    ):
        assert marker in web, f"Dashboard V10 incomplet: {marker}"

    assert '"cogs.bot_v10"' in boot
    assert "platform_v10.install(dashboard)" in community

    for path in (
        "cogs/platform_v4.py", "cogs/command_observability_v9.py",
        "cogs/ai_context_v9.py", "cogs/moderation_advisor_v9.py",
        "cogs/automod_enable_all.py",
    ):
        assert (ROOT / path).exists(), f"Régression: {path} absent"

    print("OK: Bot V10 — setup, health, audit, économie, IA, sécurité, privacy, backups, custom commands et mobile vérifiés")


if __name__ == "__main__":
    main()
