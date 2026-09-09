from __future__ import annotations

import ast
from pathlib import Path


SOURCE_PATH = Path(__file__).resolve().parents[1] / "web" / "database_dashboard.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")


def test_database_dashboard_is_valid_python():
    ast.parse(SOURCE)


def test_database_dashboard_registers_owner_only_api_surface():
    assert "/api/owner/database/status" in SOURCE
    assert "/api/owner/database/verify" in SOURCE
    assert "/api/owner/database/export" in SOURCE
    assert "is_bot_owner_id" in SOURCE
    assert "_require_csrf" in SOURCE


def test_database_dashboard_never_exposes_connection_credentials():
    lowered = SOURCE.casefold()
    assert "os.getenv(\"mongodb_uri\")" not in lowered
    assert "os.environ[\"mongodb_uri\"]" not in lowered
    assert "connection_uri" in lowered
    assert '"contains_connection_uri": false' in lowered
    assert '"contains_credentials": false' in lowered


def test_database_dashboard_export_is_diagnostic_only():
    assert '"kind": "database-diagnostic"' in SOURCE
    assert '"contains_rows": False' in SOURCE
    assert '"tables": snapshot.get("tables", [])' in SOURCE


def test_database_dashboard_shows_real_sqlite_backend_and_mongodb_link():
    assert '"backend": "SQLite"' in SOURCE
    assert "https://cloud.mongodb.com/" in SOURCE
    assert "Le dashboard n'active jamais un changement de backend automatiquement" in SOURCE
