#!/usr/bin/env python3
"""Audit CI des fonctions de préparation production SentriX."""
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
os.environ.setdefault("DATABASE_PATH", "/tmp/sentrix-production-readiness-audit.db")

from cogs import production_readiness_runtime as production
from database.db import Database

EXPECTED_TABLES = {
    "guild_readiness_audits",
    "retention_policies",
    "retention_runs",
    "privacy_actions",
    "production_readiness_state",
}


def static_audit() -> None:
    source = (ROOT / "cogs" / "production_readiness_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    required = (
        "audit_guild_configuration",
        "run_retention",
        "_privacy_export",
        "_privacy_purge",
        "_security_readiness",
        "_security_infra",
        "_security_retention",
        "_security_privacy",
        "main-db-snapshot",
        "data-retention",
    )
    for marker in required:
        assert marker in source, f"Production marker manquant: {marker}"
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("web"), "Le runtime production bot ne doit pas dépendre du dashboard"
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("web") for alias in node.names)
    # Aucune nouvelle racine publique décorée.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            text = ast.unparse(decorator)
            assert not any(x in text for x in ("commands.command", "commands.group", "commands.hybrid_command", "app_commands.command")), text

    boot = (ROOT / "railway_boot.py").read_text(encoding="utf-8")
    assert "DurableDatabaseReplica" in boot
    assert "restore_latest_if_needed" in boot
    assert 'reason="graceful_shutdown"' in boot
    canary = (ROOT / "railway_canary_boot.py").read_text(encoding="utf-8")
    assert "CANARY_BOT_TOKEN" in canary
    assert "CANARY_GUILD_ID" in canary
    health = (ROOT / "web" / "production_health.py").read_text(encoding="utf-8")
    assert "database_ok" in health and "discord_ready" in health
    uptime = (ROOT / ".github" / "workflows" / "uptime.yml").read_text(encoding="utf-8")
    assert "*/5 * * * *" in uptime
    assert "discord_ready" in uptime


async def schema_audit() -> None:
    path = pathlib.Path(os.environ["DATABASE_PATH"])
    path.unlink(missing_ok=True)
    db = Database(str(path))
    await db.connect()
    try:
        await db._conn.executescript(production.READINESS_SCHEMA)
        await db._conn.commit()
        rows = await db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        names = {str(row["name"]) for row in rows}
        assert EXPECTED_TABLES <= names, sorted(EXPECTED_TABLES - names)

        await db.execute("CREATE TABLE IF NOT EXISTS command_diagnostics (id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER,created_at INTEGER)")
        old = production.now() - 60 * 86400
        await db.execute("INSERT INTO command_diagnostics (guild_id,created_at) VALUES (?,?)", (123, old))
        await db.execute("INSERT INTO command_diagnostics (guild_id,created_at) VALUES (?,?)", (123, production.now()))

        class Bot:
            pass
        bot = Bot()
        bot.db = db
        production._SCHEMA_READY = True
        result = await production.run_retention(bot, 123)
        assert result["deleted_rows"] >= 1
        row = await db.fetchone("SELECT COUNT(*) AS n FROM command_diagnostics WHERE guild_id=123")
        assert int(row["n"]) == 1
    finally:
        await db.close()
        production._SCHEMA_READY = False


async def runtime_audit() -> None:
    import main

    bot = main.BotAllInOne()
    await bot.db.connect()
    try:
        for ext in main.EXTENSIONS:
            await bot.load_extension(ext)
            if ext == "cogs.ai":
                break
        runtime = bot.get_cog("ProductionReadinessRuntime")
        assert runtime is not None, "ProductionReadinessRuntime absent"
        for name in ("readiness", "infra", "retention", "privacy"):
            assert bot.get_command(f"security {name}") is not None, f"+security {name} absent"
            assert bot.get_command(name) is None, f"Racine publique inattendue: {name}"
    finally:
        runtime = bot.get_cog("ProductionReadinessRuntime")
        if runtime:
            runtime.maintenance.cancel()
        await bot.db.close()
        production._SCHEMA_READY = False


async def main_audit() -> None:
    static_audit()
    await schema_audit()
    await runtime_audit()
    print("OK: readiness 0-100, infra, durabilité, rétention, privacy, canary et monitoring externe audités")


if __name__ == "__main__":
    asyncio.run(main_audit())
