"""Enregistre un node-agent avec un token aleatoire.

Usage:
  SENTRIX_ADMIN_DATABASE_URL=postgresql://... python ops/execution/register_node.py node-eu-1
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import sys

import asyncpg

from libs.ids import uuid7

CELL_ID = "01920000-0000-7000-8000-000000000001"


async def run(name: str) -> None:
    dsn = os.environ["SENTRIX_ADMIN_DATABASE_URL"]
    token = secrets.token_urlsafe(48)
    node_id = uuid7()
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "INSERT INTO nodes (id, cell_id, name, agent_token_sha256) VALUES ($1, $2, $3, $4)",
            node_id,
            CELL_ID,
            name,
            hashlib.sha256(token.encode()).digest(),
        )
    finally:
        await conn.close()
    print(f"SENTRIX_NODE_ID={node_id}")
    print(f"SENTRIX_NODE_TOKEN={token}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: register_node.py <node-name>")
    asyncio.run(run(sys.argv[1]))
