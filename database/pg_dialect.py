"""Traduction du SQL SQLite de SentriX vers PostgreSQL.

SentriX contient ~2 700 appels SQL écrits pour SQLite (190 fichiers). Les réécrire
tous à la main serait le meilleur moyen de casser le bot ; ils passent tous par
``Database`` (database/db.py) — c'est donc là, et seulement là, que la traduction
se fait. Chaque règle correspond à une différence MESURÉE entre les deux moteurs
(tests/test_pg_dialect.py) :

* paramètres ``?`` -> ``$1, $2…`` ;
* ``INSERT OR IGNORE`` -> ``ON CONFLICT DO NOTHING`` ;
* ``INSERT OR REPLACE`` / ``REPLACE INTO`` -> upsert sur la clé primaire ;
* ``ON CONFLICT … DO UPDATE SET n = n + excluded.n`` : Postgres juge ``n``
  ambigu, il faut ``table.n`` à droite du ``=`` ;
* ``strftime('%s','now')`` -> heure Unix ;
* ``LIKE`` -> ``ILIKE`` (SQLite ignore la casse ASCII, Postgres non) ;
* ``MAX(a, b)`` / ``MIN(a, b)`` scalaires -> ``GREATEST`` / ``LEAST`` ;
* DDL : ``INTEGER`` -> ``BIGINT`` (identifiants Discord sur 64 bits),
  ``INTEGER PRIMARY KEY [AUTOINCREMENT]`` -> identité, ``REAL``, ``BLOB``,
  ``BOOLEAN`` (SQLite y range 0/1), et une colonne ``rowid`` sur chaque table
  (le code s'en sert pour trier et pour ``lastrowid``).

Le texte entre apostrophes (les données) n'est jamais modifié.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable

# --------------------------------------------------------------------------- découpage


def _segments(sql: str) -> list[tuple[str, str]]:
    """Découpe en ('code' | 'str' | 'ident' | 'comment', texte), sans rien perdre."""
    out: list[tuple[str, str]] = []
    i, n = 0, len(sql)
    buf = []
    while i < n:
        ch = sql[i]
        if ch == "'" :
            if buf:
                out.append(("code", "".join(buf)))
                buf = []
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append(("str", sql[i:j + 1]))
            i = j + 1
            continue
        if ch == '"':
            if buf:
                out.append(("code", "".join(buf)))
                buf = []
            j = sql.find('"', i + 1)
            j = n - 1 if j == -1 else j
            out.append(("ident", sql[i:j + 1]))
            i = j + 1
            continue
        if ch == "-" and sql.startswith("--", i):
            if buf:
                out.append(("code", "".join(buf)))
                buf = []
            j = sql.find("\n", i)
            j = n if j == -1 else j
            out.append(("comment", sql[i:j]))
            i = j
            continue
        buf.append(ch)
        i += 1
    if buf:
        out.append(("code", "".join(buf)))
    return out


def _join(segments: Iterable[tuple[str, str]]) -> str:
    return "".join(text for _kind, text in segments)


def _map_code(sql: str, fn: Callable[[str], str]) -> str:
    return _join((kind, fn(text) if kind == "code" else text) for kind, text in _segments(sql))


def code_only(sql: str) -> str:
    """Le SQL sans chaînes ni commentaires (pour les détections)."""
    return " ".join(text for kind, text in _segments(sql) if kind in ("code", "ident"))


def split_statements(script: str) -> list[str]:
    """Découpe un script sur les « ; » de premier niveau (hors chaînes)."""
    statements, current = [], []
    for kind, text in _segments(script):
        if kind != "code":
            current.append(text)
            continue
        start = 0
        for idx, ch in enumerate(text):
            if ch == ";":
                current.append(text[start:idx])
                stmt = "".join(current).strip()
                if stmt and code_only(stmt).strip():
                    statements.append(stmt)
                current, start = [], idx + 1
        current.append(text[start:])
    tail = "".join(current).strip()
    if tail and code_only(tail).strip():
        statements.append(tail)
    return statements


# --------------------------------------------------------------------------- paramètres


def number_placeholders(sql: str) -> tuple[str, int]:
    count = 0

    def repl(text: str) -> str:
        nonlocal count
        out = []
        for ch in text:
            if ch == "?":
                count += 1
                out.append(f"${count}")
            else:
                out.append(ch)
        return "".join(out)

    return _map_code(sql, repl), count


# --------------------------------------------------------------------------- DDL

_TYPE_MAP = [
    (re.compile(r"^(UNSIGNED\s+BIG\s+INT|BIGINT|INTEGER|INT|TINYINT|SMALLINT|MEDIUMINT)\b", re.I), "BIGINT"),
    (re.compile(r"^(BOOLEAN|BOOL)\b", re.I), "BIGINT"),
    (re.compile(r"^(REAL|DOUBLE(\s+PRECISION)?|FLOAT|NUMERIC|DECIMAL)\b", re.I), "DOUBLE PRECISION"),
    (re.compile(r"^BLOB\b", re.I), "BYTEA"),
    (re.compile(r"^(DATETIME|TIMESTAMP|DATE|VARCHAR(\s*\(\s*\d+\s*\))?|CHAR(\s*\(\s*\d+\s*\))?|JSON|STRING)\b", re.I), "TEXT"),
]
_CONSTRAINT_START = re.compile(r"^\s*(PRIMARY\s+KEY|UNIQUE|CHECK|FOREIGN\s+KEY|CONSTRAINT)\b", re.I)
_COLUMN_DEF = re.compile(r"^(\s*)(\"[^\"]+\"|\w+)(\s+)(.*)$", re.S)


def _column_definition(part: str) -> str:
    """« nom TYPE contraintes » : seul le TYPE (et AUTOINCREMENT) change, jamais le nom."""
    if _CONSTRAINT_START.match(code_only(part)):
        return _map_code(part, _clean_constraints)
    m = _COLUMN_DEF.match(part)
    if not m:
        return part
    lead, name, space, rest = m.groups()
    if re.match(r"^INTEGER\s+PRIMARY\s+KEY", rest, re.I):
        rest = re.sub(r"^INTEGER\s+PRIMARY\s+KEY(\s+AUTOINCREMENT)?", "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY", rest, flags=re.I)
    else:
        for pattern, replacement in _TYPE_MAP:
            if pattern.match(rest):
                rest = pattern.sub(replacement, rest, count=1)
                break
    return lead + name + space + _map_code(rest, _clean_constraints)


def _clean_constraints(text: str) -> str:
    text = re.sub(r"\bAUTOINCREMENT\b", "", text, flags=re.I)
    text = re.sub(r"\bCOLLATE\s+NOCASE\b", "", text, flags=re.I)
    text = re.sub(r"\bON\s+CONFLICT\s+(REPLACE|IGNORE|ABORT|FAIL|ROLLBACK)\b", "", text, flags=re.I)
    return text


def _alter_table(sql: str) -> str:
    m = re.match(r"^(\s*ALTER\s+TABLE\s+[\w\"]+\s+ADD\s+(?:COLUMN\s+)?)(.*)$", sql, re.I | re.S)
    if not m:
        return sql
    return m.group(1) + _column_definition(m.group(2))


_CREATE_TABLE = re.compile(r"^\s*CREATE\s+(?:TEMP\w*\s+)?TABLE\s+(IF\s+NOT\s+EXISTS\s+)?([\w\"]+)\s*\(", re.I | re.S)
_INT_PK_COLUMN = re.compile(r"^\s*([\w\"]+)\s+INTEGER\s+PRIMARY\s+KEY", re.I)


def _top_level_parts(body: str) -> list[str]:
    parts, depth, current = [], 0, []
    for kind, text in _segments(body):
        if kind != "code":
            current.append(text)
            continue
        start = 0
        for idx, ch in enumerate(text):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                current.append(text[start:idx])
                parts.append("".join(current))
                current, start = [], idx + 1
        current.append(text[start:])
    parts.append("".join(current))
    return parts


def _matching_paren(sql: str, open_index: int) -> int:
    depth = 0
    for kind, text, offset in _segments_with_offsets(sql):
        if kind != "code":
            continue
        for idx, ch in enumerate(text):
            pos = offset + idx
            if pos < open_index:
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return pos
    return -1


def _segments_with_offsets(sql: str):
    offset = 0
    for kind, text in _segments(sql):
        yield kind, text, offset
        offset += len(text)


def translate_create_table(sql: str) -> str:
    match = _CREATE_TABLE.match(sql)
    if not match:
        return sql
    open_index = match.end() - 1
    close_index = _matching_paren(sql, open_index)
    if close_index == -1:
        return sql
    body = sql[open_index + 1:close_index]
    parts = _top_level_parts(body)
    int_pk = None
    for part in parts:
        m = _INT_PK_COLUMN.match(code_only(part))
        if m:
            int_pk = m.group(1)
            break
    has_rowid = any(re.match(r"^\s*\"?rowid\"?\s", code_only(p), re.I) for p in parts)
    new_parts = [_column_definition(part) for part in parts]
    if not has_rowid:
        if int_pk:
            new_parts.append(f" rowid BIGINT GENERATED ALWAYS AS ({int_pk}) STORED")
        else:
            new_parts.append(" rowid BIGINT GENERATED BY DEFAULT AS IDENTITY")
    head = _map_code(sql[:open_index + 1], lambda t: t)
    tail = _map_code(sql[close_index:], lambda t: re.sub(r"\bWITHOUT\s+ROWID\b", "", t, flags=re.I))
    return head + ",".join(new_parts) + tail


# --------------------------------------------------------------------------- expressions

_NOW = re.compile(r"strftime\s*\(\s*'%s'\s*,\s*'now'\s*\)", re.I)


def _now(text: str) -> str:
    return text


def _scalar_minmax(text: str) -> str:
    """MAX(a, b) / MIN(a, b) à plusieurs arguments -> GREATEST / LEAST."""
    out, i = [], 0
    pattern = re.compile(r"\b(MAX|MIN)\s*\(", re.I)
    while True:
        m = pattern.search(text, i)
        if not m:
            out.append(text[i:])
            break
        start = m.end() - 1
        depth, j = 0, start
        top_comma = False
        while j < len(text):
            ch = text[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            elif ch == "," and depth == 1:
                top_comma = True
            j += 1
        out.append(text[i:m.start()])
        if top_comma and j < len(text):
            name = "GREATEST" if m.group(1).upper() == "MAX" else "LEAST"
            out.append(f"{name}(")
        else:
            out.append(text[m.start():m.end()])
        i = m.end()
    return "".join(out)


_COMPARISON = re.compile(r"(<>|!=|<=|>=|=|<|>|\bIS\b|\bIN\b|\bLIKE\b|\bILIKE\b|\bAND\b|\bOR\b|\bNOT\b)", re.I)


def _boolean_aggregates(text: str) -> str:
    """SUM(vote = 1) : SQLite additionne des 0/1, Postgres refuse SUM(boolean)."""
    out, i = [], 0
    pattern = re.compile(r"\b(SUM|AVG|TOTAL)\s*\(", re.I)
    while True:
        m = pattern.search(text, i)
        if not m:
            out.append(text[i:])
            break
        start = m.end()
        depth, j = 1, start
        while j < len(text) and depth:
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
            j += 1
        inner = text[start:j - 1]
        # Comparaison au premier niveau seulement (pas dans un CASE déjà écrit).
        flat, d = [], 0
        for ch in inner:
            if ch == "(":
                d += 1
            elif ch == ")":
                d -= 1
            flat.append(ch if d == 0 else " ")
        top = "".join(flat)
        out.append(text[i:m.start()])
        if _COMPARISON.search(top) and not re.match(r"\s*(CASE|DISTINCT)\b", inner, re.I):
            out.append(f"{m.group(1)}(CASE WHEN ({inner}) THEN 1 ELSE 0 END)")
        else:
            out.append(text[m.start():j])
        i = j
    return "".join(out)


def _expressions(text: str) -> str:
    text = re.sub(r"\bNOT\s+LIKE\b", "NOT ILIKE", text, flags=re.I)
    text = re.sub(r"(?<!NOT )\bLIKE\b", "ILIKE", text, flags=re.I)
    text = re.sub(r"(?<![=!<>])==(?!=)", "=", text)
    text = re.sub(r"\bIFNULL\s*\(", "COALESCE(", text, flags=re.I)
    text = _scalar_minmax(text)
    text = _boolean_aggregates(text)
    return text


def _sql_now(sql: str) -> str:
    """strftime('%s','now') : les apostrophes sont dans des segments 'str', on
    travaille donc sur le texte complet avec une expression exacte."""
    return _NOW.sub("(EXTRACT(EPOCH FROM now())::BIGINT)", sql)


# --------------------------------------------------------------------------- INSERT

_INSERT = re.compile(
    r"^\s*(INSERT\s+OR\s+(IGNORE|REPLACE)\s+INTO|REPLACE\s+INTO|INSERT\s+INTO)\s+([\w\"]+)\s*(\(([^)]*)\))?",
    re.I | re.S,
)


@dataclass
class TableInfo:
    columns: list[str]
    primary_key: list[str]


Catalog = Callable[[str], "TableInfo | None"]


def _qualify_update_set(sql: str, table: str, columns: list[str]) -> str:
    """Dans ON CONFLICT … DO UPDATE SET a = <expr>, préfixe les colonnes de <expr>."""
    code = sql
    m = re.search(r"\bDO\s+UPDATE\s+SET\b", code, re.I)
    if not m or not columns:
        return sql
    head, rest = sql[:m.end()], sql[m.end():]
    # Fin de la clause SET : WHERE ou RETURNING de premier niveau.
    end = len(rest)
    for kw in (r"\bWHERE\b", r"\bRETURNING\b"):
        km = re.search(kw, code_only(rest), re.I)
        if km:
            # position approchée : retrouver dans rest le même mot
            real = re.search(kw, rest, re.I)
            if real:
                end = min(end, real.start())
    set_clause, tail = rest[:end], rest[end:]
    names = sorted({c for c in columns}, key=len, reverse=True)
    col_re = re.compile(r"(?<![\w.\"])(" + "|".join(re.escape(c) for c in names) + r")(?![\w\"])", re.I)
    items = _top_level_parts(set_clause)
    new_items = []
    for item in items:
        if "=" not in item:
            new_items.append(item)
            continue
        lhs, rhs = item.split("=", 1)

        def q(text: str) -> str:
            return col_re.sub(lambda mm: f"{table}.{mm.group(1)}", text)

        new_items.append(lhs + "=" + _map_code(rhs, q))
    return head + ",".join(new_items) + tail


def translate_insert(sql: str, catalog: Catalog | None) -> str:
    m = _INSERT.match(sql)
    if not m:
        return sql
    mode = (m.group(2) or ("REPLACE" if m.group(1).upper().startswith("REPLACE") else "")).upper()
    table = m.group(3).strip('"')
    cols_text = m.group(5)
    sql = "INSERT INTO " + sql[m.start(3):]
    info = catalog(table) if catalog else None
    has_conflict = re.search(r"\bON\s+CONFLICT\b", code_only(sql), re.I) is not None
    returning = re.search(r"\bRETURNING\b", code_only(sql), re.I) is not None
    if mode == "IGNORE" and not has_conflict:
        sql = _append_before_returning(sql, " ON CONFLICT DO NOTHING")
    elif mode == "REPLACE" and not has_conflict and info is not None and info.primary_key:
        cols = [c.strip().strip('"') for c in cols_text.split(",")] if cols_text else list(info.columns)
        updates = [c for c in cols if c.lower() not in {p.lower() for p in info.primary_key} and c.lower() != "rowid"]
        target = ", ".join(info.primary_key)
        if updates:
            action = "DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in updates)
        else:
            action = "DO NOTHING"
        sql = _append_before_returning(sql, f" ON CONFLICT ({target}) {action}")
    if info is not None:
        sql = _qualify_update_set(sql, table, info.columns)
    if not returning and info is not None and "rowid" in {c.lower() for c in info.columns}:
        sql = sql.rstrip().rstrip(";") + " RETURNING rowid"
    return sql


def _append_before_returning(sql: str, clause: str) -> str:
    m = re.search(r"\bRETURNING\b", sql, re.I)
    if m and re.search(r"\bRETURNING\b", code_only(sql), re.I):
        return sql[:m.start()].rstrip() + clause + " " + sql[m.start():]
    return sql.rstrip().rstrip(";") + clause


# --------------------------------------------------------------------------- point d'entrée


@dataclass
class Translated:
    sql: str
    kind: str          # "select" | "dml" | "ddl" | "pragma" | "noop" | "other"
    table: str | None = None
    params: int = 0


_FIRST_WORD = re.compile(r"^\s*(\w+)", re.S)


def translate(sql: str, catalog: Catalog | None = None) -> Translated:
    # Les commentaires « -- » ne servent à rien côté base, et en tête d'instruction
    # ils masquaient le CREATE TABLE à reconnaître.
    stripped = _join(seg for seg in _segments(sql) if seg[0] != "comment").strip().rstrip(";").strip()
    first = (_FIRST_WORD.match(code_only(stripped)) or _FIRST_WORD.match("x")).group(1).upper()
    if first == "PRAGMA":
        return Translated(stripped, "pragma")
    if first in ("BEGIN", "COMMIT", "END", "ROLLBACK", "SAVEPOINT", "RELEASE", "VACUUM", "ANALYZE", "REINDEX"):
        return Translated(stripped, "noop" if first in ("VACUUM", "ANALYZE", "REINDEX") else "tx")
    text = _sql_now(stripped)
    if first == "CREATE" and re.match(r"^\s*CREATE\s+(TEMP\w*\s+)?TABLE", code_only(text), re.I):
        text = translate_create_table(text)
        kind = "ddl"
    elif first == "ALTER":
        text = _alter_table(text)
        kind = "ddl"
    elif first in ("CREATE", "DROP"):
        text = _map_code(text, lambda t: re.sub(r"\bCOLLATE\s+NOCASE\b", "", t, flags=re.I))
        kind = "ddl"
    else:
        text = _map_code(text, _expressions)
        kind = "select" if first in ("SELECT", "WITH") else "dml" if first in ("INSERT", "UPDATE", "DELETE", "REPLACE") else "other"
    table = None
    if first in ("INSERT", "REPLACE"):
        im = _INSERT.match(text)
        table = im.group(3).strip('"') if im else None
        text = translate_insert(text, catalog)
    text, count = number_placeholders(text)
    return Translated(text, kind, table, count)


__all__ = ["translate", "Translated", "TableInfo", "split_statements", "code_only", "number_placeholders"]
