#!/usr/bin/env python3
"""Register a builder/orchestrator machine and emit a private env file once."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import secrets
from pathlib import Path

import asyncpg

from libs.ids import uuid7


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("builder", "orchestrator"))
    parser.add_argument("name")
    parser.add_argument("output", type=Path)
    return parser


def _write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


async def _register(kind: str, name: str, output: Path) -> None:
    dsn = os.environ.get("MIGRATIONS_DATABASE_URL")
    if not dsn:
        raise RuntimeError("MIGRATIONS_DATABASE_URL is required")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")

    worker_id = uuid7()
    token = secrets.token_urlsafe(48)
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        exists = await conn.fetchval("SELECT 1 FROM control_workers WHERE name = $1", name)
        if exists is not None:
            raise RuntimeError(f"control worker already exists: {name}")
        await conn.execute(
            """
            INSERT INTO control_workers (id, kind, name, token_sha256)
            VALUES ($1, $2, $3, $4)
            """,
            worker_id,
            kind,
            name,
            digest,
        )
    finally:
        await conn.close()

    try:
        _write_private(
            output,
            "\n".join(
                (
                    f"SENTRIX_CONTROL_WORKER_ID={worker_id}",
                    f"SENTRIX_CONTROL_WORKER_TOKEN={token}",
                    "",
                )
            ),
        )
    except BaseException:
        cleanup = await asyncpg.connect(dsn, statement_cache_size=0)
        try:
            await cleanup.execute("DELETE FROM control_workers WHERE id = $1", worker_id)
        finally:
            await cleanup.close()
        raise

    print(f"registered {kind} worker {name}; credentials written to {output}")


def main() -> None:
    args = _parser().parse_args()
    asyncio.run(_register(args.kind, args.name, args.output))


if __name__ == "__main__":
    main()
