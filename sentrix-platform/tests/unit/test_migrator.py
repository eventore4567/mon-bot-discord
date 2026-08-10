from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from libs.db.migrator import MigrationDriftError, apply_all, discover


class _Tx(AbstractAsyncContextManager[None]):
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


class FakeConnection:
    def __init__(self, applied: dict[str, str] | None = None) -> None:
        self.applied = dict(applied or {})
        self.executed_sql: list[str] = []

    async def execute(self, sql: str, *args: Any) -> str:
        self.executed_sql.append(sql)
        if sql.startswith("INSERT INTO schema_migrations"):
            version, checksum = args
            self.applied[str(version)] = str(checksum)
        return "OK"

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, str]]:
        del args
        assert "schema_migrations" in sql
        return [
            {"version": version, "checksum": checksum}
            for version, checksum in sorted(self.applied.items())
        ]

    def transaction(self) -> _Tx:
        return _Tx()


def _write(path: Path, content: str = "SELECT 1;\n") -> None:
    path.write_text(content, encoding="utf-8")


def test_discover_orders_numbered_migrations(tmp_path: Path) -> None:
    _write(tmp_path / "0002_second.sql")
    _write(tmp_path / "0001_first.sql")

    migrations = discover(tmp_path)

    assert [migration.version for migration in migrations] == ["0001", "0002"]


def test_discover_rejects_invalid_filename(tmp_path: Path) -> None:
    _write(tmp_path / "migration.sql")

    with pytest.raises(ValueError, match="nom de migration invalide"):
        discover(tmp_path)


def test_discover_rejects_duplicate_versions(tmp_path: Path) -> None:
    _write(tmp_path / "0001_first.sql")
    _write(tmp_path / "0001_second.sql")

    with pytest.raises(ValueError, match="numeros de migration dupliques"):
        discover(tmp_path)


@pytest.mark.asyncio
async def test_apply_all_is_idempotent_and_detects_drift(tmp_path: Path) -> None:
    migration_path = tmp_path / "0001_first.sql"
    _write(migration_path, "SELECT 1;\n")
    conn = FakeConnection()

    first = await apply_all(conn, tmp_path)  # type: ignore[arg-type]
    second = await apply_all(conn, tmp_path)  # type: ignore[arg-type]

    assert first == ["0001"]
    assert second == []

    _write(migration_path, "SELECT 2;\n")
    with pytest.raises(MigrationDriftError):
        await apply_all(conn, tmp_path)  # type: ignore[arg-type]
