"""Connexion PostgreSQL qui se comporte comme la connexion aiosqlite de SentriX.

``Database`` (database/db.py) et quelques modules qui touchent ``db._conn``
attendent l'interface d'aiosqlite : ``execute`` qui rend un curseur
(``fetchone``, ``fetchall``, ``rowcount``, ``lastrowid``, ``description``),
``commit``, ``rollback``, ``executescript``, des lignes lisibles par nom OU par
position, et les exceptions de ``sqlite3`` (le code attrape
``sqlite3.IntegrityError`` ou cherche « duplicate column » dans le message).

Ce qui est reproduit fidèlement :

* transactions implicites comme le module sqlite3 : la première écriture ouvre
  une transaction, ``commit()`` la ferme ; une erreur n'annule que l'instruction
  fautive (SAVEPOINT), comme SQLite — Postgres, lui, empoisonnerait toute la
  transaction ;
* une seule connexion d'écriture, sérialisée (comme aiosqlite) ; les lectures
  hors transaction partent sur un pool, en parallèle — c'est le gain d'échelle ;
* typage souple : chaque paramètre est converti vers le type que Postgres attend
  (un identifiant Discord passé en texte devient un entier, et inversement) ;
* ``SUM``/``AVG`` rendent des ``Decimal`` côté Postgres : ramenés à int/float.

Activé seulement si ``SENTRIX_DB_BACKEND=postgres`` (database/db.py) ; SQLite
reste le défaut.
"""
from __future__ import annotations

import asyncio
import decimal
import logging
import re
import sqlite3
from typing import Any, Iterable, Sequence

from database import pg_dialect
from database.pg_dialect import TableInfo

logger = logging.getLogger("bot.pg")

try:
    import asyncpg  # type: ignore
except Exception:  # pragma: no cover
    asyncpg = None


# --------------------------------------------------------------------------- lignes


class PgRow:
    """Ligne façon sqlite3.Row : r["col"] (insensible à la casse), r[0], keys(), dict(r)."""

    __slots__ = ("_keys", "_values", "_index")

    def __init__(self, keys: Sequence[str], values: Sequence[Any]):
        self._keys = list(keys)
        self._values = [_plain(v) for v in values]
        self._index = {}
        for i, k in enumerate(self._keys):
            self._index.setdefault(k, i)
            self._index.setdefault(k.lower(), i)

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._values[key]
        try:
            return self._values[self._index[key]]
        except KeyError:
            try:
                return self._values[self._index[str(key).lower()]]
            except KeyError:
                raise IndexError(f"No item with that key: {key}") from None

    def keys(self) -> list[str]:
        return list(self._keys)

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __eq__(self, other) -> bool:
        if isinstance(other, PgRow):
            return self._keys == other._keys and self._values == other._values
        return NotImplemented

    def __hash__(self) -> int:
        return hash(tuple(self._values))

    def __repr__(self) -> str:
        return f"PgRow({dict(zip(self._keys, self._values))!r})"


def _plain(value: Any) -> Any:
    if isinstance(value, decimal.Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, memoryview):
        return bytes(value)
    return value


# --------------------------------------------------------------------------- curseur


class PgCursor:
    def __init__(self, rows: list[PgRow] | None = None, rowcount: int = -1, lastrowid: int | None = None,
                 keys: Sequence[str] | None = None):
        self._rows = rows or []
        self._pos = 0
        self.rowcount = rowcount
        self.lastrowid = lastrowid
        self.description = tuple((k, None, None, None, None, None, None) for k in (keys or [])) or None

    async def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    async def fetchall(self):
        rows = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rows

    async def fetchmany(self, size: int = 1):
        rows = self._rows[self._pos:self._pos + size]
        self._pos += len(rows)
        return rows

    async def close(self) -> None:
        return None

    def __aiter__(self):
        return self

    async def __anext__(self):
        row = await self.fetchone()
        if row is None:
            raise StopAsyncIteration
        return row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


# --------------------------------------------------------------------------- erreurs


def _sqlite_error(exc: Exception) -> Exception:
    """Une erreur Postgres traduite dans la famille sqlite3 que le code attrape déjà."""
    if asyncpg is None:
        return exc
    message = str(exc)
    if isinstance(exc, (asyncpg.UniqueViolationError, asyncpg.ForeignKeyViolationError,
                        asyncpg.NotNullViolationError, asyncpg.CheckViolationError)):
        if isinstance(exc, asyncpg.UniqueViolationError):
            message = f"UNIQUE constraint failed: {message}"
        elif isinstance(exc, asyncpg.NotNullViolationError):
            message = f"NOT NULL constraint failed: {message}"
        err = sqlite3.IntegrityError(message)
    elif isinstance(exc, asyncpg.DuplicateColumnError):
        m = re.search(r'column "([^"]+)"', message)
        err = sqlite3.OperationalError(f"duplicate column name: {m.group(1) if m else message}")
    elif isinstance(exc, asyncpg.UndefinedTableError):
        m = re.search(r'relation "([^"]+)"', message)
        err = sqlite3.OperationalError(f"no such table: {m.group(1) if m else message}")
    elif isinstance(exc, asyncpg.UndefinedColumnError):
        m = re.search(r'column "?([^" ]+)"? does not exist', message)
        err = sqlite3.OperationalError(f"no such column: {m.group(1) if m else message}")
    elif isinstance(exc, asyncpg.DuplicateTableError):
        err = sqlite3.OperationalError(f"table already exists: {message}")
    elif isinstance(exc, (asyncpg.PostgresSyntaxError, asyncpg.PostgresError)):
        err = sqlite3.OperationalError(message)
    else:
        return exc
    err.__cause__ = exc
    return err


# --------------------------------------------------------------------------- paramètres

_INT_TYPES = {"int2", "int4", "int8", "numeric", "oid"}
_FLOAT_TYPES = {"float4", "float8"}
_TEXT_TYPES = {"text", "varchar", "bpchar", "name", "unknown"}


def _coerce(value: Any, type_name: str) -> Any:
    if value is None:
        return None
    if type_name in _INT_TYPES:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value) if value.is_integer() else value
        if isinstance(value, str):
            text = value.strip()
            if re.fullmatch(r"[+-]?\d+", text):
                return int(text)
            try:
                number = float(text)
                return int(number) if number.is_integer() else number
            except ValueError:
                return value
        return value
    if type_name in _FLOAT_TYPES:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return value
        return value
    if type_name in _TEXT_TYPES:
        if isinstance(value, str):
            return value
        if isinstance(value, bool):
            return str(int(value))
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, (bytes, bytearray)):
            return bytes(value).decode("utf-8", "replace")
        return str(value)
    if type_name == "bytea":
        if isinstance(value, str):
            return value.encode("utf-8")
        return value
    if type_name == "bool":
        return bool(value)
    return value


# --------------------------------------------------------------------------- connexion


class PgConnection:
    """Remplace aiosqlite.Connection pour Database."""

    row_factory = None  # compatibilité : Database pose aiosqlite.Row, ignoré ici

    def __init__(self, main, pool, schema: str):
        self._main = main
        self._pool = pool
        self.schema = schema
        self._lock = asyncio.Lock()
        self._tx = None
        self._tables: dict[str, TableInfo] = {}
        self._param_types: dict[str, list[str]] = {}
        self._statements: dict[str, Any] = {}
        self._savepoints = 0
        # last_insert_rowid() de SQLite : le dernier rowid inséré sur cette connexion.
        self._last_rowid: int | None = None

    # ------------------------------------------------------------ ouverture

    @classmethod
    async def connect(cls, url: str, schema: str = "sentrix", pool_size: int = 8) -> "PgConnection":
        if asyncpg is None:
            raise RuntimeError("asyncpg est requis pour SENTRIX_DB_BACKEND=postgres")
        schema = re.sub(r"[^a-zA-Z0-9_]", "_", schema) or "sentrix"
        bootstrap = await asyncpg.connect(url)
        try:
            await bootstrap.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        finally:
            await bootstrap.close()
        # search_path en paramètre de DÉMARRAGE : le pool d'asyncpg fait RESET ALL à
        # chaque libération, ce qui effaçait un SET search_path (tables « introuvables »).
        settings = {"search_path": f'"{schema}"'}
        main = await asyncpg.connect(url, server_settings=settings)
        pool = await asyncpg.create_pool(
            url, min_size=1, max_size=max(1, pool_size), server_settings=settings
        )
        self = cls(main, pool, schema)
        await main.execute(
            """
            CREATE OR REPLACE VIEW sqlite_master AS
            SELECT 'table'::text AS type, table_name::text AS name, table_name::text AS tbl_name,
                   0::bigint AS rootpage, NULL::text AS sql
            FROM information_schema.tables
            WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'
            UNION ALL
            SELECT 'index'::text, indexname::text, tablename::text, 0::bigint, indexdef::text
            FROM pg_indexes WHERE schemaname = current_schema()
            """
        )
        await self._load_catalog()
        return self

    async def close(self) -> None:
        try:
            if self._tx is not None:
                await self._tx.commit()
        except Exception:
            logger.exception("Fermeture : transaction en cours non validée")
        self._tx = None
        await self._main.close()
        await self._pool.close()

    # ------------------------------------------------------------ catalogue

    async def _load_catalog(self, table: str | None = None) -> None:
        where = "c.table_schema = current_schema()"
        args: list[Any] = []
        if table:
            where += " AND c.table_name = $1"
            args.append(table.lower())
        rows = await self._main.fetch(
            f"SELECT c.table_name, c.column_name FROM information_schema.columns c "
            f"WHERE {where} ORDER BY c.table_name, c.ordinal_position",
            *args,
        )
        columns: dict[str, list[str]] = {}
        for r in rows:
            columns.setdefault(r["table_name"], []).append(r["column_name"])
        keys = await self._main.fetch(
            """
            SELECT t.relname AS table_name, i.indisprimary AS is_pk,
                   array_agg(a.attname ORDER BY array_position(i.indkey::int2[], a.attnum)) AS cols
            FROM pg_index i
            JOIN pg_class t ON t.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(i.indkey)
            WHERE n.nspname = current_schema() AND (i.indisprimary OR i.indisunique)
              AND i.indpred IS NULL
            GROUP BY t.relname, i.indexrelid, i.indisprimary
            ORDER BY i.indisprimary DESC
            """
        )
        pks: dict[str, list[str]] = {}
        for r in keys:
            if r["table_name"] in columns and r["table_name"] not in pks and list(r["cols"]) != ["rowid"]:
                pks[r["table_name"]] = list(r["cols"])
        if table is None:
            self._tables = {}
        else:
            self._tables.pop(table.lower(), None)
        for name, cols in columns.items():
            self._tables[name] = TableInfo(columns=cols, primary_key=pks.get(name, []))

    def _catalog(self, table: str) -> TableInfo | None:
        return self._tables.get(table.lower())

    # ------------------------------------------------------------ exécution

    async def execute(self, sql: str, parameters: Iterable[Any] | dict | None = None) -> PgCursor:
        params = tuple(parameters or ())
        if "last_insert_rowid" in sql:
            sql = _LAST_ROWID.sub(str(int(self._last_rowid or 0)), sql)
        translated = pg_dialect.translate(sql, self._catalog)
        kind = translated.kind
        if kind == "pragma":
            return await self._pragma(translated.sql)
        if kind == "noop":
            return PgCursor()
        if kind == "tx":
            word = translated.sql.split()[0].upper()
            if word in ("COMMIT", "END"):
                await self.commit()
            elif word == "ROLLBACK":
                await self.rollback()
            elif word == "BEGIN":
                async with self._lock:
                    await self._begin()
            return PgCursor()
        if kind == "select" and self._tx is None:
            return await self._run(self._pool, translated, params, pooled=True)
        async with self._lock:
            opened_here = False
            if kind == "dml" and self._tx is None:
                await self._begin()
                opened_here = True
            if self._tx is not None and not opened_here:
                # Comme SQLite : une instruction en échec n'annule qu'elle-même.
                self._savepoints += 1
                name = f"sx_sp_{self._savepoints}"
                await self._main.execute(f"SAVEPOINT {name}")
                try:
                    cursor = await self._run(self._main, translated, params)
                except Exception:
                    await self._main.execute(f"ROLLBACK TO SAVEPOINT {name}")
                    raise
                await self._main.execute(f"RELEASE SAVEPOINT {name}")
            else:
                try:
                    cursor = await self._run(self._main, translated, params)
                except Exception:
                    if opened_here and self._tx is not None:
                        tx, self._tx = self._tx, None
                        await tx.rollback()
                    raise
            if kind == "ddl":
                # Sous le verrou : la connexion principale ne sert qu'à une opération à la fois.
                await self._refresh_after_ddl(translated.sql)
        return cursor

    async def execute_and_commit(self, sql: str, parameters: Iterable[Any] | None = None) -> PgCursor:
        """``execute`` puis ``commit`` (chemin de Database.execute).

        Sans transaction ouverte, une écriture isolée part en autocommit : un seul
        aller-retour au lieu de trois (BEGIN, instruction, COMMIT). Mesuré : sous
        une rafale de spam, c'était la différence entre 0,3 s et 4 s de réaction.
        """
        params = tuple(parameters or ())
        translated = pg_dialect.translate(sql, self._catalog)
        if translated.kind in ("dml", "other") and self._tx is None:
            async with self._lock:
                if self._tx is None:
                    return await self._run(self._main, translated, params)
        cursor = await self.execute(sql, params)
        await self.commit()
        return cursor

    async def _begin(self) -> None:
        self._tx = self._main.transaction()
        await self._tx.start()

    async def _run(self, target, translated: pg_dialect.Translated, params: tuple, *, pooled: bool = False) -> PgCursor:
        sql = translated.sql
        try:
            if pooled:
                async with target.acquire() as conn:
                    if translated.params == 0 and not params:
                        records = await conn.fetch(sql)
                    else:
                        types = await self._types_for(sql, conn)
                        records = await conn.fetch(sql, *self._args(params, types))
                return self._cursor(records, "SELECT", translated)
            if translated.params == 0 and not params and (
                translated.kind in ("ddl", "other") or ";" in pg_dialect.code_only(sql)
            ):
                status = await target.execute(sql)
                return PgCursor(rowcount=_rowcount(status))
            stmt = self._statements.get(sql)
            if stmt is None:
                stmt = await target.prepare(sql)
                if len(self._statements) > 2000:
                    self._statements.clear()
                self._statements[sql] = stmt
                self._param_types.setdefault(sql, [t.name for t in stmt.get_parameters()])
            types = self._param_types.get(sql) or [t.name for t in stmt.get_parameters()]
            records = await stmt.fetch(*self._args(params, types))
            return self._cursor(records, stmt.get_statusmsg() or "", translated)
        except Exception as exc:  # noqa: BLE001
            mapped = _sqlite_error(exc)
            if mapped is exc:
                raise
            logger.debug("SQL Postgres refusé : %s\n%s", exc, sql)
            raise mapped from exc

    @staticmethod
    def _args(params: tuple, types: list[str]) -> list[Any]:
        return [_coerce(v, types[i] if i < len(types) else "unknown") for i, v in enumerate(params)]

    async def _types_for(self, sql: str, conn) -> list[str]:
        types = self._param_types.get(sql)
        if types is None:
            stmt = await conn.prepare(sql)
            types = [t.name for t in stmt.get_parameters()]
            if len(self._param_types) > 5000:
                self._param_types.clear()
            self._param_types[sql] = types
        return types

    def _cursor(self, records, status: str, translated: pg_dialect.Translated) -> PgCursor:
        keys = list(records[0].keys()) if records else []
        auto_returning = translated.kind == "dml" and translated.sql.rstrip().endswith(" RETURNING rowid")
        lastrowid = None
        if auto_returning:
            if records:
                lastrowid = records[-1]["rowid"]
            rows: list[PgRow] = []
            keys = []
        else:
            rows = [PgRow(list(r.keys()), list(r.values())) for r in records]
            if translated.kind == "dml" and records and "rowid" in records[-1].keys():
                lastrowid = records[-1]["rowid"]
        rowcount = _rowcount(status)
        if translated.kind == "select":
            rowcount = -1
        if lastrowid is not None:
            self._last_rowid = int(lastrowid)
        return PgCursor(rows, rowcount, lastrowid, keys)

    async def _refresh_after_ddl(self, sql: str) -> None:
        m = re.search(r"\b(?:TABLE|ON)\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?\"?(\w+)\"?", sql, re.I)
        try:
            await self._load_catalog(m.group(1) if m else None)
        except Exception:
            logger.debug("Catalogue Postgres non rafraîchi après : %s", sql, exc_info=True)

    async def _read(self, _label: str, sql: str, *args):
        """Lecture interne : sur le pool, ou sur la connexion principale si une
        transaction y est ouverte (sinon on ne verrait pas ses changements)."""
        if self._tx is None:
            return await self._pool.fetch(sql, *args)
        async with self._lock:
            return await self._main.fetch(sql, *args)

    async def _pragma(self, sql: str) -> PgCursor:
        m = re.match(r"PRAGMA\s+(\w+)\s*(?:\(\s*['\"]?(\w+)['\"]?\s*\)|=\s*(\S+))?", sql, re.I)
        name = (m.group(1) if m else "").lower()
        arg = m.group(2) if m else None
        if name == "table_info" and arg:
            records = await self._read(
                "PRAGMA_TABLE_INFO", 
                """
                SELECT (c.ordinal_position - 1)::bigint AS cid, c.column_name::text AS name,
                       upper(c.data_type)::text AS type,
                       (c.is_nullable = 'NO')::int::bigint AS notnull, c.column_default::text AS dflt_value,
                       COALESCE((SELECT 1 FROM information_schema.table_constraints tc
                                 JOIN information_schema.key_column_usage k
                                   ON k.constraint_name = tc.constraint_name AND k.table_schema = tc.table_schema
                                 WHERE tc.table_schema = current_schema() AND tc.table_name = c.table_name
                                   AND tc.constraint_type = 'PRIMARY KEY' AND k.column_name = c.column_name
                                 LIMIT 1), 0)::bigint AS pk
                FROM information_schema.columns c
                WHERE c.table_schema = current_schema() AND c.table_name = $1 AND c.column_name <> 'rowid'
                ORDER BY c.ordinal_position
                """,
                arg.lower(),
            )
            return PgCursor([PgRow(list(r.keys()), list(r.values())) for r in records],
                            keys=["cid", "name", "type", "notnull", "dflt_value", "pk"])
        if name in ("index_list", "index_info"):
            return PgCursor()
        if name in ("quick_check", "integrity_check"):
            return PgCursor([PgRow(["integrity_check"], ["ok"])], keys=["integrity_check"])
        return PgCursor()

    # ------------------------------------------------------------ transactions

    async def commit(self) -> None:
        if self._tx is None:
            return
        async with self._lock:
            tx, self._tx = self._tx, None
            if tx is not None:
                await tx.commit()

    async def rollback(self) -> None:
        if self._tx is None:
            return
        async with self._lock:
            tx, self._tx = self._tx, None
            if tx is not None:
                await tx.rollback()

    async def executescript(self, script: str) -> PgCursor:
        await self.commit()
        for statement in pg_dialect.split_statements(script):
            await self.execute(statement)
        await self.commit()
        return PgCursor()

    async def executemany(self, sql: str, seq_of_params: Iterable[Iterable[Any]]) -> PgCursor:
        total = 0
        for params in seq_of_params:
            cursor = await self.execute(sql, params)
            total += max(0, cursor.rowcount)
        return PgCursor(rowcount=total)

    @property
    def in_transaction(self) -> bool:
        return self._tx is not None


_LAST_ROWID = re.compile(r"\blast_insert_rowid\s*\(\s*\)", re.I)


def _rowcount(status: str) -> int:
    m = re.search(r"(\d+)\s*$", status or "")
    return int(m.group(1)) if m else -1


__all__ = ["PgConnection", "PgCursor", "PgRow"]
