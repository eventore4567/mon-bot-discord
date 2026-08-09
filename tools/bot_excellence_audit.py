#!/usr/bin/env python3
"""Audit CI du runtime d'amélioration du bot Discord (sans dashboard)."""
from __future__ import annotations

import ast
import asyncio
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
os.environ.setdefault("DATABASE_PATH", "/tmp/sentrix-bot-excellence-audit.db")

from cogs import bot_excellence_runtime as excellence
from database.db import Database


EXPECTED_TABLES = {
    "runtime_incidents",
    "runtime_health_snapshots",
    "automod_risk_events",
    "automod_risk_state",
    "economy_action_cooldowns",
    "game_outcomes",
    "game_player_stats",
    "game_daily_progress",
    "ticket_response_state",
    "ticket_runtime_reminders",
    "social_notification_deliveries",
}


def static_audit() -> None:
    path = ROOT / "cogs" / "bot_excellence_runtime.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Cette couche doit améliorer le bot existant sans gonfler le catalogue de commandes.
    forbidden = ("hybrid_command", "command(", "hybrid_group", "app_commands.command")
    for marker in forbidden:
        assert marker not in source, f"Le runtime Excellence ne doit pas créer de commande publique: {marker}"

    # Le dashboard ne doit pas être une dépendance de cette amélioration bot-only.
    assert "web." not in source
    assert "dashboard" not in source.casefold()

    required_markers = (
        "_install_ai_concurrency",
        "_install_persistent_automod",
        "_install_economy_atomicity",
        "_install_game_statistics",
        "_install_social_dedupe",
        "_ticket_reminders",
        "_repair_persistent_views",
        "_restart_failed_loops",
        "_health_snapshot",
        "_resource_guard",
        "_matchmake_tictactoe",
        "RuntimeRateLimitError",
    )
    for marker in required_markers:
        assert marker in source, f"Fonction Excellence manquante: {marker}"

    # Vérifie qu'aucun décorateur de commande n'est caché derrière une forme AST inhabituelle.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            text = ast.unparse(decorator)
            assert not any(token in text for token in ("commands.command", "commands.hybrid_command", "commands.hybrid_group", "app_commands.command")), text


async def schema_audit() -> None:
    path = os.environ["DATABASE_PATH"]
    try:
        pathlib.Path(path).unlink()
    except FileNotFoundError:
        pass
    db = Database(path)
    await db.connect()
    try:
        await db._conn.executescript(excellence.RUNTIME_SCHEMA)
        await db._conn.commit()
        rows = await db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        names = {row["name"] for row in rows}
        missing = EXPECTED_TABLES - names
        assert not missing, f"Tables Excellence manquantes: {sorted(missing)}"

        # Contraintes anti-double action critiques.
        sql = excellence.RUNTIME_SCHEMA
        assert "PRIMARY KEY (subscription_id, item_id)" in sql
        assert "session_id TEXT PRIMARY KEY" in sql
        assert "PRIMARY KEY (guild_id, user_id, action)" in sql
        assert "PRIMARY KEY (ticket_id, last_activity_at, reminder_type)" in sql
    finally:
        await db.close()


def integration_wiring_audit() -> None:
    source = (ROOT / "cogs" / "stability_runtime.py").read_text(encoding="utf-8")
    assert "bot_excellence_runtime" in source
    assert "install_bot_excellence_runtime(bot, name)" in source


async def main() -> None:
    static_audit()
    integration_wiring_audit()
    await schema_audit()
    print("OK: runtime Excellence bot-only, schéma, anti-abus, économie, jeux, tickets, notifications et diagnostics audités")


if __name__ == "__main__":
    asyncio.run(main())
