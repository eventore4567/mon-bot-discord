"""Static regression gate for Bot V13 production hardening."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V13 = ROOT / "cogs" / "bot_v13_production.py"
LOADER = ROOT / "cogs" / "remove_code_command" / "__init__.py"


def require(source: str, needle: str, label: str) -> None:
    if needle not in source:
        raise AssertionError(f"V13 gate: missing {label}: {needle}")


def main() -> None:
    source = V13.read_text(encoding="utf-8")
    loader = LOADER.read_text(encoding="utf-8")

    compile(source, str(V13), "exec")
    compile(loader, str(LOADER), "exec")
    tree = ast.parse(source)

    # Bot-only layer: no public command roots and no dashboard wiring.
    forbidden_decorators = {"command", "hybrid_command", "group", "hybrid_group"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                name = getattr(target, "attr", None) or getattr(target, "id", None)
                if name in forbidden_decorators:
                    raise AssertionError(f"V13 gate: public command decorator found on {node.name}")
    if "web." in source or "dashboard" in source.casefold():
        # The module docstring may say it does not change the dashboard; imports/routes are forbidden.
        imports_dashboard = any(
            isinstance(node, (ast.Import, ast.ImportFrom))
            and any("web" in alias.name or "dashboard" in alias.name for alias in node.names)
            for node in ast.walk(tree)
        )
        if imports_dashboard:
            raise AssertionError("V13 gate: dashboard/web import is forbidden")

    # 1. Correct production security routing.
    for field in ("log_automod", "log_moderation", "error_channel", "log_channel"):
        require(source, f'"{field}"', f"security route {field}")
    require(source, "_sentrix_v13_log_route", "security routing marker")

    # 2. Live canary: real Discord API, real DB CRUD, optional OpenAI request.
    require(source, "fetch_user", "Discord API canary")
    require(source, "v13_canary_probe", "database CRUD canary")
    require(source, "ai_service.test_connection", "OpenAI canary")
    require(source, "sentrix_canary_status", "canary monitoring status")

    # 3. V12 game-form metrics are surfaced to existing player commands.
    for marker in ("v12_game_form", "current_streak", "longest_streak", "total_reward"):
        require(source, marker, f"game stats {marker}")
    require(source, '"gameprofile"', "gameprofile integration")
    require(source, '"gamestats"', "gamestats integration")

    # 4. One localized + legacy-compatible ticket watcher; old loader is gone.
    require(source, "status IN ('ouvert','open')", "unified ticket statuses")
    require(source, "machine.ticket_watch_loop.cancel", "V12 duplicate watcher cancellation")
    if "install_v12_ticket_sla" in loader:
        raise AssertionError("V13 gate: legacy V12 ticket SLA is still loaded")
    require(loader, "install_v13_production", "V13 loader")

    # 5. Optional distributed infra heals after transient failures.
    require(source, "infra.reconnect", "PostgreSQL/Redis reconnect")
    require(source, "postgres_configured", "PostgreSQL health")
    require(source, "redis_configured", "Redis health")

    # 6. Backup/recovery uses SQLite online backup + checks both archive and restored DB.
    require(source, "src.backup", "SQLite online backup API")
    require(source, "PRAGMA integrity_check", "backup integrity check")
    require(source, "PRAGMA quick_check", "post-restore verification")
    require(source, ".pre-restore-v13", "rollback snapshot")

    # 24/7 supervision: all critical V13 loops are restarted if they stop.
    require(source, "supervisor_loop", "runtime supervisor")
    for loop_name in ("ticket_sla_loop", "live_canary_loop", "infra_watch_loop"):
        require(source, f"self.{loop_name}", f"supervised loop {loop_name}")

    print("Bot V13 production gate: OK")


if __name__ == "__main__":
    main()
