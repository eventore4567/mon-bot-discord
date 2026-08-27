from __future__ import annotations

import ast
import re
from pathlib import Path

from cogs import member_data_retention_v17 as retention

ROOT = Path(__file__).resolve().parents[1]


def _compact_sql(text: str) -> str:
    return re.sub(r"\s+", " ", text).casefold()


def test_core_progress_schema_is_scoped_by_guild_and_user():
    source = _compact_sql((ROOT / "database" / "db.py").read_text(encoding="utf-8"))
    for table in ("levels", "message_counts", "economy", "profiles", "voice_totals"):
        match = re.search(
            rf"create table if not exists {table} \((.*?)\);",
            source,
            flags=re.DOTALL,
        )
        assert match, f"schema table missing: {table}"
        body = match.group(1)
        assert "guild_id" in body
        assert "user_id" in body
        assert "primary key (guild_id, user_id)" in body


def test_sql_guard_blocks_destructive_progress_deletes():
    assert retention.destructive_progress_tables(
        "DELETE FROM levels WHERE guild_id = ? AND user_id = ?"
    ) == {"levels"}
    assert retention.destructive_progress_tables(
        "delete   from economy where guild_id=?"
    ) == {"economy"}
    assert retention.destructive_progress_tables(
        "DROP TABLE IF EXISTS message_counts"
    ) == {"message_counts"}
    assert retention.destructive_progress_tables(
        "UPDATE levels SET xp = xp + 10 WHERE guild_id=? AND user_id=?"
    ) == set()
    # Une suppression d'inventaire peut être une consommation/vente normale : elle est
    # auditée dans les events leave/ban, mais pas bloquée globalement.
    assert retention.destructive_progress_tables(
        "DELETE FROM inventory WHERE guild_id=? AND user_id=? AND item_name=?"
    ) == set()


def test_explicit_reset_context_is_separate_from_moderation():
    assert retention._EXPLICIT_DATA_RESET.get() is False
    with retention.explicit_data_reset():
        assert retention._EXPLICIT_DATA_RESET.get() is True
    assert retention._EXPLICIT_DATA_RESET.get() is False


def test_leave_and_ban_listeners_never_delete_member_progress():
    dangerous_calls = {
        "reset_economy",
        "reset_levels",
        "reset_reputation",
        "clear_member_data",
        "delete_member_data",
    }
    failures: list[str] = []

    for path in ROOT.rglob("*.py"):
        if any(part in {".git", ".venv", "venv", "__pycache__"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
        except (UnicodeDecodeError, SyntaxError):
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            if node.name not in {"on_member_remove", "on_member_ban"}:
                continue
            segment = ast.get_source_segment(text, node) or ""
            lowered = segment.casefold()
            for table in retention.AUDITED_MEMBER_PROGRESS_TABLES:
                if re.search(rf"delete\s+from\s+[`\"\[]?{re.escape(table)}\b", lowered):
                    failures.append(f"{path}:{node.lineno} deletes {table}")
            for call in dangerous_calls:
                if call in lowered:
                    failures.append(f"{path}:{node.lineno} calls {call}")

    assert not failures, "Progress deletion found in leave/ban listeners: " + "; ".join(failures)


def test_member_join_is_non_destructive_and_restores_only_missing_rows():
    source = (ROOT / "cogs" / "member_data_retention_v17.py").read_text(encoding="utf-8")
    assert "INSERT OR IGNORE INTO levels" in source
    assert "INSERT OR IGNORE INTO message_counts" in source
    assert "INSERT OR IGNORE INTO economy" in source
    assert "_restore_missing_core_rows" in source
    assert "latest_retained_snapshot" in source
    join_start = source.index("async def on_member_join")
    join_source = source[join_start:]
    assert "DELETE FROM" not in join_source


def test_levels_messages_and_economy_are_database_backed():
    levels = (ROOT / "cogs" / "levels.py").read_text(encoding="utf-8")
    economy = (ROOT / "cogs" / "economy.py").read_text(encoding="utf-8")
    db = (ROOT / "database" / "db.py").read_text(encoding="utf-8")

    assert "UPDATE message_counts SET count = count + 1" in levels
    assert "UPDATE levels SET xp = ?, level = ?" in levels
    assert "await self._conn.commit()" in db
    assert "ensure_economy" in economy
    assert "add_balance" in economy
    assert "deposit" in economy
    assert "withdraw" in economy


def test_destructive_reset_commands_require_confirmation_layer():
    source = (ROOT / "cogs" / "member_data_retention_v17.py").read_text(encoding="utf-8")
    for command in ("reset-levels", "reset-economy", "represet"):
        assert f'"{command}"' in source
    assert "ResetConfirmationView" in source
    assert "Confirmer le reset" in source
    assert "explicit_data_reset" in source
    assert "Un ban ne déclenche jamais cette suppression" in source


def test_durable_storage_is_hardened_beyond_graceful_shutdown():
    source = (ROOT / "cogs" / "member_data_retention_v17.py").read_text(encoding="utf-8")
    assert "PRAGMA synchronous=FULL" in source
    assert "_periodic_snapshot_loop" in source
    assert 'durable.snapshot(reason=reason, clean_shutdown=False)' in source
    assert 'self._request_durable_snapshot("member_remove")' in source
    assert 'self._request_durable_snapshot("member_ban")' in source


def test_retention_cog_is_loaded_last_in_railway_runtime():
    boot = (ROOT / "railway_boot.py").read_text(encoding="utf-8")
    marker = 'bot_main.EXTENSIONS.append("cogs.member_data_retention_v17")'
    assert marker in boot
    assert boot.index(marker) > boot.index('bot_main.EXTENSIONS.append("cogs.final_stability_guard")')
