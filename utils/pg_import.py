"""Import unique de la base SQLite de SentriX dans PostgreSQL.

Appelé au démarrage quand ``SENTRIX_DB_BACKEND=postgres`` et que le schéma
Postgres n'a jamais été importé (marqueur ``sentrix_pg_import``). Le démarrage
haute disponibilité garantit qu'un seul service — le leader — le fait.

Source : la dernière sauvegarde SQLite stockée dans Postgres
(``sentrix_main_db_snapshots``, écrite par l'ancien processus en s'arrêtant),
sinon le fichier local.

Ce qui ne doit jamais arriver, et ce qui l'empêche :

* perdre une valeur parce que SQLite est permissif : une colonne déclarée
  INTEGER peut contenir du texte. Le type Postgres est choisi d'après les
  valeurs RÉELLES de la colonne (texte -> TEXT, décimaux -> DOUBLE PRECISION) ;
* perdre l'ordre d'insertion : le ``rowid`` SQLite est recopié tel quel ;
* casser les identifiants auto-incrémentés : les séquences repartent après le
  plus grand identifiant importé ;
* importer à moitié : tout se fait dans une transaction, puis le nombre de
  lignes de chaque table est comparé à la source ; en cas d'écart, rien n'est
  validé et le bot ne démarre pas sur Postgres.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from database import pg_dialect

logger = logging.getLogger("bot.pg-import")

MARKER_TABLE = "sentrix_pg_import"
_INT = {"bigint", "integer", "smallint"}


def _read_sqlite(path: Path) -> dict[str, Any]:
    """Tout ce qu'il faut de la source, lu en lecture seule."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    try:
        tables = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "AND sql IS NOT NULL ORDER BY name"
        ).fetchall()
        indexes = conn.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        ).fetchall()
        data: dict[str, Any] = {"tables": [], "indexes": [(n, t, s) for n, t, s in indexes]}
        for name, sql in tables:
            cols = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
            column_names = [c[1] for c in cols]
            observed: dict[str, set[str]] = {}
            for col in column_names:
                kinds = conn.execute(
                    f'SELECT DISTINCT typeof("{col}") FROM "{name}"'
                ).fetchall()
                observed[col] = {k[0] for k in kinds}
            without_rowid = bool(re.search(r"WITHOUT\s+ROWID", sql or "", re.I))
            select_cols = ", ".join(f'"{c}"' for c in column_names)
            if without_rowid:
                rows = conn.execute(f'SELECT {select_cols} FROM "{name}"').fetchall()
                rowids = None
            else:
                fetched = conn.execute(f'SELECT rowid, {select_cols} FROM "{name}" ORDER BY rowid').fetchall()
                rowids = [r[0] for r in fetched]
                rows = [r[1:] for r in fetched]
            data["tables"].append({
                "name": name, "sql": sql, "columns": column_names, "observed": observed,
                "rows": rows, "rowids": rowids,
            })
        return data
    finally:
        conn.close()


def _value(value: Any, pg_type: str) -> Any:
    if value is None:
        return None
    if pg_type in _INT:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        return int(str(value).strip())
    if pg_type == "double precision":
        return float(value)
    if pg_type == "bytea":
        return value if isinstance(value, (bytes, bytearray)) else str(value).encode("utf-8")
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", "replace")
    return str(value) if not isinstance(value, str) else value


def _needed_type(declared_pg: str, observed: set[str]) -> str | None:
    """Le type Postgres à imposer si les valeurs réelles ne tiennent pas dans le type déclaré."""
    observed = observed - {"null"}
    if not observed:
        return None
    if declared_pg in _INT:
        if "text" in observed or "blob" in observed:
            return "TEXT"
        if "real" in observed:
            return "DOUBLE PRECISION"
    if declared_pg == "double precision" and ("text" in observed or "blob" in observed):
        return "TEXT"
    if declared_pg == "bytea" and observed - {"blob"}:
        return "TEXT"
    return None


async def already_imported(conn) -> bool:
    exists = await conn.fetchval(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = $1",
        MARKER_TABLE,
    )
    if not exists:
        return False
    return bool(await conn.fetchval(f"SELECT COUNT(*) FROM {MARKER_TABLE} WHERE status = 'done'"))


async def import_sqlite(url: str, schema: str, source: Path, *, source_label: str = "") -> dict[str, Any]:
    """Importe ``source`` dans le schéma ``schema`` ; rend le rapport (tables, lignes)."""
    import asyncpg  # type: ignore

    schema = re.sub(r"[^a-zA-Z0-9_]", "_", schema)
    data = await asyncio.to_thread(_read_sqlite, source)
    started = time.monotonic()
    conn = await asyncpg.connect(url, server_settings={"search_path": f'"{schema}"'})
    report: dict[str, Any] = {"source": source_label or str(source), "tables": {}, "retyped": {}}
    try:
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        if await already_imported(conn):
            return {"skipped": "already_imported"}
        async with conn.transaction():
            for table in data["tables"]:
                name = table["name"]
                ddl = pg_dialect.translate(table["sql"]).sql
                await conn.execute(f'DROP TABLE IF EXISTS "{name}" CASCADE')
                await conn.execute(ddl)
                types = {
                    r["column_name"]: r["data_type"]
                    for r in await conn.fetch(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = $1",
                        name.lower(),
                    )
                }
                identity = {
                    r["column_name"]: r["is_generated"]
                    for r in await conn.fetch(
                        "SELECT column_name, is_identity, is_generated FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = $1 "
                        "AND (is_identity = 'YES' OR is_generated = 'ALWAYS')",
                        name.lower(),
                    )
                }
                for col in table["columns"]:
                    needed = _needed_type(types.get(col.lower(), ""), table["observed"].get(col, set()))
                    if needed and identity.get(col.lower()) != "ALWAYS":
                        if col.lower() in identity:
                            await conn.execute(f'ALTER TABLE "{name}" ALTER COLUMN "{col.lower()}" DROP IDENTITY IF EXISTS')
                        await conn.execute(
                            f'ALTER TABLE "{name}" ALTER COLUMN "{col.lower()}" TYPE {needed} USING "{col.lower()}"::text'
                            if needed == "TEXT" else
                            f'ALTER TABLE "{name}" ALTER COLUMN "{col.lower()}" TYPE {needed}'
                        )
                        types[col.lower()] = needed.lower()
                        report["retyped"][f"{name}.{col}"] = needed
                columns = [c.lower() for c in table["columns"]]
                copy_rowid = table["rowids"] is not None and types.get("rowid") and identity.get("rowid") != "ALWAYS"
                records = []
                for index, row in enumerate(table["rows"]):
                    values = [_value(v, types.get(c, "text")) for v, c in zip(row, columns)]
                    if copy_rowid:
                        values.append(int(table["rowids"][index]))
                    records.append(tuple(values))
                target_columns = columns + (["rowid"] if copy_rowid else [])
                if records:
                    await conn.copy_records_to_table(name.lower(), records=records, columns=target_columns)
                # Les identités repartent après le plus grand identifiant importé.
                for col in [c for c in columns + ["rowid"] if c in identity and identity[c] != "ALWAYS"]:
                    await conn.execute(
                        f"SELECT setval(pg_get_serial_sequence('\"{name.lower()}\"', '{col}'), "
                        f"GREATEST(COALESCE((SELECT MAX(\"{col}\") FROM \"{name.lower()}\"), 0), 1))"
                    )
                count = await conn.fetchval(f'SELECT COUNT(*) FROM "{name.lower()}"')
                if count != len(table["rows"]):
                    raise RuntimeError(f"{name} : {count} lignes importées pour {len(table['rows'])} dans la source")
                report["tables"][name] = count
            skipped_indexes = []
            for index_name, _table, sql in data["indexes"]:
                try:
                    async with conn.transaction():
                        await conn.execute(pg_dialect.translate(sql).sql)
                except Exception as exc:  # noqa: BLE001
                    skipped_indexes.append(f"{index_name}: {type(exc).__name__}")
            report["skipped_indexes"] = skipped_indexes
            report["rows"] = sum(report["tables"].values())
            report["seconds"] = round(time.monotonic() - started, 1)
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {MARKER_TABLE} (id BIGSERIAL PRIMARY KEY, status TEXT NOT NULL, "
                "source TEXT, report TEXT, finished_at BIGINT NOT NULL)"
            )
            await conn.execute(
                f"INSERT INTO {MARKER_TABLE} (status, source, report, finished_at) VALUES ('done', $1, $2, $3)",
                report["source"], json.dumps(report, ensure_ascii=False), int(time.time()),
            )
        logger.warning(
            "Import SQLite -> PostgreSQL terminé : %s tables, %s lignes, %s s, %s colonnes retypées, %s index ignorés.",
            len(report["tables"]), report["rows"], report["seconds"], len(report["retyped"]),
            len(report["skipped_indexes"]),
        )
        return report
    finally:
        await conn.close()


async def ensure_imported(url: str, schema: str, local_sqlite: Path, durable=None) -> dict[str, Any]:
    """Au démarrage : importe une fois, depuis la dernière sauvegarde sinon le fichier local."""
    import asyncpg  # type: ignore

    conn = await asyncpg.connect(url, server_settings={"search_path": f'"{schema}"'})
    try:
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        if await already_imported(conn):
            return {"skipped": "already_imported"}
    finally:
        await conn.close()

    source, label, temp = None, "", None
    if durable is not None and getattr(durable, "configured", False):
        import tempfile

        from utils.durable_database import DurableDatabaseReplica

        temp = Path(tempfile.mkdtemp(prefix="sentrix-pg-import-")) / "source.db"
        replica = DurableDatabaseReplica(str(temp))
        replica.force_restore = True
        try:
            if await replica.connect():
                result = await replica.restore_latest_if_needed()
                if result.get("restored"):
                    source, label = temp, f"snapshot #{result.get('snapshot_id')} ({result.get('created_at')})"
        finally:
            await replica.close()
    if source is None and local_sqlite.exists() and local_sqlite.stat().st_size > 0:
        source, label = local_sqlite, f"fichier local {local_sqlite}"
    if source is None:
        logger.warning("Aucune base SQLite à importer : PostgreSQL démarre vide.")
        conn = await asyncpg.connect(url, server_settings={"search_path": f'"{schema}"'})
        try:
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {MARKER_TABLE} (id BIGSERIAL PRIMARY KEY, status TEXT NOT NULL, "
                "source TEXT, report TEXT, finished_at BIGINT NOT NULL)"
            )
            await conn.execute(
                f"INSERT INTO {MARKER_TABLE} (status, source, report, finished_at) VALUES ('done', 'vide', '{{}}', $1)",
                int(time.time()),
            )
        finally:
            await conn.close()
        return {"imported": False, "reason": "no_source"}
    try:
        return await import_sqlite(url, schema, source, source_label=label)
    finally:
        if temp is not None:
            try:
                temp.unlink(missing_ok=True)
                temp.parent.rmdir()
            except OSError:
                pass


__all__ = ["import_sqlite", "ensure_imported", "already_imported", "MARKER_TABLE"]
