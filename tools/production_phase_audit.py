#!/usr/bin/env python3
"""Gate CI final de la phase production/stabilité SentriX.

Ce test complète les audits spécialisés déjà exécutés par Stability : il vérifie le
câblage du nouveau runtime SLO, la persistance après redémarrage, l'agrégation des
métriques sans écriture par commande, le self-test Canary et la reconnexion infra.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database
from cogs import production_phase_runtime as phase
from utils.enterprise_infra import EnterpriseInfra

EXPECTED_TABLES = {
    "production_boots",
    "production_slo_samples",
    "production_slo_state",
    "production_command_metrics",
}


def static_audit() -> None:
    source = (ROOT / "cogs" / "production_phase_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    required = (
        "_record_boot",
        "_mark_clean_shutdown",
        "_install_close_guard",
        "_install_missing_argument_help",
        "_flush_command_metrics",
        "_recover_infra_if_needed",
        "production_slo_samples",
        "production_command_metrics",
    )
    for marker in required:
        assert marker in source, f"Production phase manquante: {marker}"

    # Le runtime de stabilité ne doit pas gonfler le catalogue public.
    forbidden = (
        "commands.command",
        "commands.hybrid_command",
        "commands.group",
        "commands.hybrid_group",
        "app_commands.command",
    )
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            text = ast.unparse(decorator)
            assert not any(token in text for token in forbidden), f"Nouvelle commande publique interdite: {text}"

    stability = (ROOT / "cogs" / "stability_runtime.py").read_text(encoding="utf-8")
    assert "production_phase_runtime" in stability
    assert "install_production_phase_runtime(bot, name)" in stability

    canary = (ROOT / "railway_canary_boot.py").read_text(encoding="utf-8")
    for marker in ("_run_canary_self_test", '"self_test"', "PRAGMA quick_check", 'required_commands = ("help", "ping", "security", "ticket", "ban")'):
        assert marker in canary, f"Canary gate incomplet: {marker}"
    assert "bot._persistence_check_done = True" in canary, "Le Canary recommencerait à MP le diagnostic volume"

    assert inspect.iscoroutinefunction(EnterpriseInfra.reconnect), "EnterpriseInfra.reconnect doit être async"


async def schema_audit(path: str) -> None:
    db = Database(path)
    await db.connect()
    try:
        await db._conn.executescript(phase.RUNTIME_SCHEMA)
        await db._conn.commit()
        rows = await db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        names = {str(row["name"]) for row in rows}
        missing = EXPECTED_TABLES - names
        assert not missing, f"Tables production manquantes: {sorted(missing)}"
    finally:
        await db.close()


async def restart_persistence_audit(path: str) -> None:
    """Écrit des données métier, ferme SQLite, rouvre et exige les mêmes valeurs."""
    guild_id = 991001
    user_id = 991002
    db = Database(path)
    await db.connect()
    try:
        await db.execute("INSERT OR REPLACE INTO guild_config (guild_id,prefix) VALUES (?,?)", (guild_id, "!"))
        await db.execute(
            "INSERT INTO warnings (guild_id,user_id,moderator_id,reason,timestamp) VALUES (?,?,?,?,?)",
            (guild_id, user_id, 991003, "restart-probe", 123456),
        )
        await db.execute(
            "INSERT OR REPLACE INTO economy (guild_id,user_id,cash,bank) VALUES (?,?,?,?)",
            (guild_id, user_id, 4321, 8765),
        )
        await db.execute(
            "INSERT INTO tickets (guild_id,channel_id,user_id,status,created_at) VALUES (?,?,?,?,?)",
            (guild_id, 991004, user_id, "ouvert", 123456),
        )
    finally:
        await db.close()

    reopened = Database(path)
    await reopened.connect()
    try:
        conf = await reopened.fetchone("SELECT prefix FROM guild_config WHERE guild_id=?", (guild_id,))
        warning = await reopened.fetchone("SELECT reason FROM warnings WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        money = await reopened.fetchone("SELECT cash,bank FROM economy WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        ticket = await reopened.fetchone("SELECT status FROM tickets WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        assert conf and conf["prefix"] == "!"
        assert warning and warning["reason"] == "restart-probe"
        assert money and int(money["cash"]) == 4321 and int(money["bank"]) == 8765
        assert ticket and ticket["status"] == "ouvert"
        check = await reopened.fetchone("PRAGMA quick_check")
        assert check and str(check[0]).casefold() == "ok"
    finally:
        await reopened.close()


async def runtime_audit(path: str) -> None:
    os.environ["DATABASE_PATH"] = path
    import main

    bot = main.BotAllInOne()
    await bot.db.connect()
    try:
        for extension in main.EXTENSIONS:
            await bot.load_extension(extension)
        bot._prune_redundant_commands()

        runtime = bot.get_cog("ProductionPhaseRuntime")
        assert runtime is not None, "ProductionPhaseRuntime absent"
        assert getattr(bot, "_sentrix_production_boot_id", None), "boot production non enregistré"

        error_handler = getattr(bot.on_command_error, "__func__", bot.on_command_error)
        assert getattr(error_handler, "_sentrix_root_help_error", False), "message MissingRequiredArgument root-help non installé"

        help_command = bot.get_command("help")
        assert help_command is not None
        assert not getattr(help_command, "clean_params", None), "+help expose encore un paramètre"

        # L'agrégateur doit écrire une ligne par commande/minute, pas une écriture SQL à
        # chaque invocation. On injecte trois appels dans le buffer puis on flush.
        runtime._command_buffer["ping"] = [3.0, 1.0, 90.0, 50.0]
        await runtime._flush_command_metrics()
        row = await bot.db.fetchone(
            "SELECT calls,errors,total_ms,max_ms FROM production_command_metrics WHERE command_name='ping' ORDER BY hour_bucket DESC LIMIT 1"
        )
        assert row and int(row["calls"]) == 3 and int(row["errors"]) == 1
        assert float(row["total_ms"]) == 90.0 and float(row["max_ms"]) == 50.0

        tables = await bot.db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        names = {str(row["name"]) for row in tables}
        assert EXPECTED_TABLES <= names
    finally:
        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await bot.db.close()


async def main_audit() -> None:
    static_audit()
    with tempfile.TemporaryDirectory(prefix="sentrix-production-phase-") as folder:
        schema_path = str(pathlib.Path(folder) / "schema.db")
        restart_path = str(pathlib.Path(folder) / "restart.db")
        runtime_path = str(pathlib.Path(folder) / "runtime.db")
        await schema_audit(schema_path)
        await restart_persistence_audit(restart_path)
        await runtime_audit(runtime_path)
    print("OK: phase production — SLO, recovery, restart persistence, Canary gate, help et métriques validés")


if __name__ == "__main__":
    asyncio.run(main_audit())
