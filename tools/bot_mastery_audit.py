#!/usr/bin/env python3
"""Audit CI du runtime Bot Mastery (bot Discord uniquement)."""
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
os.environ.setdefault("DATABASE_PATH", "/tmp/sentrix-bot-mastery-audit.db")

from cogs import bot_mastery_runtime as mastery
from database.db import Database

EXPECTED_TABLES = {
    "mastery_join_risk",
    "mastery_nuke_actions",
    "command_access_rules",
    "moderation_evidence",
    "adaptive_sanction_advice",
    "ticket_mastery_state",
    "music_recovery_state",
    "api_circuit_state",
    "database_health",
    "command_diagnostics",
    "runtime_error_groups",
    "runtime_module_state",
    "component_probe_results",
    "economy_abuse_state",
    "economy_transfer_events",
    "onboarding_state",
    "game_weekly_progress",
    "shutdown_state",
}

REQUIRED_MARKERS = (
    "_command_access_check",
    "_security_access",
    "_security_evidence",
    "_install_moderation_evidence",
    "_install_ai_mastery",
    "_install_game_mastery",
    "_install_music_mastery",
    "_install_graceful_close",
    "_ticket_reassignment_pass",
    "_restart_stalled_loops",
    "_probe_components",
    "_database_maintenance",
    "_recover_after_restart",
    "_rollback_nuke_v3",
    "_economy_abuse_check",
    "_send_onboarding",
    "on_webhooks_update",
    "on_guild_role_delete",
    "on_member_remove",
)


def static_audit() -> None:
    source = (ROOT / "cogs" / "bot_mastery_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "dashboard" not in source.casefold(), "Mastery doit rester indépendant du dashboard"
    assert "web." not in source, "Mastery ne doit importer aucune route web"
    for marker in REQUIRED_MARKERS:
        assert marker in source, f"Fonction Mastery manquante: {marker}"

    # Aucune nouvelle commande RACINE décorée : access/evidence sont uniquement ajoutées
    # comme sous-commandes du groupe +security déjà existant.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            text = ast.unparse(decorator)
            assert not any(token in text for token in (
                "commands.command", "commands.group", "commands.hybrid_command",
                "commands.hybrid_group", "app_commands.command",
            )), f"Nouvelle racine Mastery détectée: {text}"

    bootstrap = (ROOT / "cogs" / "remove_code_command.py").read_text(encoding="utf-8")
    assert "install_bot_mastery" in bootstrap
    assert "await install_bot_mastery(bot" in bootstrap
    assert "_finish_mastery_after_ready" in bootstrap


async def schema_audit() -> None:
    path = os.environ["DATABASE_PATH"]
    try:
        pathlib.Path(path).unlink()
    except FileNotFoundError:
        pass
    db = Database(path)
    await db.connect()
    try:
        await db._conn.executescript(mastery.RUNTIME_SCHEMA)
        await db._conn.commit()
        rows = await db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        names = {row["name"] for row in rows}
        missing = EXPECTED_TABLES - names
        assert not missing, f"Tables Mastery manquantes: {sorted(missing)}"
        sql = mastery.RUNTIME_SCHEMA
        assert "PRIMARY KEY (guild_id, command_name, role_id)" in sql
        assert "PRIMARY KEY (guild_id, user_id, week)" in sql
        assert "fingerprint TEXT PRIMARY KEY" in sql
        assert "guild_id INTEGER PRIMARY KEY" in sql  # music recovery
    finally:
        await db.close()


async def runtime_audit() -> None:
    import main

    bot = main.BotAllInOne()
    await bot.db.connect()
    try:
        # Ordre identique au vrai démarrage jusqu'à l'IA : remove_code_command y installe
        # Operations + Mastery après que moderation/automod/security/tickets existent.
        for ext in main.EXTENSIONS:
            await bot.load_extension(ext)
            if ext == "cogs.ai":
                break
        runtime = bot.get_cog("BotMasteryRuntime")
        assert runtime is not None, "Cog BotMasteryRuntime non installé"
        assert bot.get_command("security access") is not None, "+security access absent"
        assert bot.get_command("security evidence") is not None, "+security evidence absent"
        # Aucune racine access/evidence indépendante.
        assert bot.get_command("access") is None
        assert bot.get_command("evidence") is None
        assert mastery._ACCESS_CHECK_PATCHED
        assert mastery._MODERATION_PATCHED
        assert mastery._AI_PATCHED
        # Le patch jeu enveloppe utils.game_rewards et peut être posé avant le cog jeux.
        assert mastery._GAME_PATCHED
        # Music est chargé plus tard : l'installation READY le posera en production.
        assert not mastery._MUSIC_PATCHED
    finally:
        runtime = bot.get_cog("BotMasteryRuntime")
        if runtime:
            runtime.maintenance.cancel()
        await bot.db.close()


async def main_audit() -> None:
    static_audit()
    await schema_audit()
    await runtime_audit()
    print("OK: Bot Mastery — anti-raid/nuke V3, accès, preuves, tickets, recovery, musique, IA, DB, diagnostics, jeux, économie, onboarding et arrêt gracieux audités")


if __name__ == "__main__":
    asyncio.run(main_audit())