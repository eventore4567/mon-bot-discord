#!/usr/bin/env python3
"""Démarre le bot sur PostgreSQL (schéma neuf) et compte les erreurs SQL.

    SENTRIX_POSTGRES_URL=postgresql://… python3 tools/pg_boot_probe.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import sys
import uuid
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
os.environ["SENTRIX_DB_BACKEND"] = "postgres"
os.environ.setdefault("SENTRIX_PG_SCHEMA", "probe_" + uuid.uuid4().hex[:8])

ERRORS: list[str] = []


class Capture(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.ERROR:
            text = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                text += f" | {type(record.exc_info[1]).__name__}: {record.exc_info[1]}"
            ERRORS.append(text)


async def main() -> int:
    logging.getLogger().addHandler(Capture())
    import sentrix_e2e_harness as h

    bot = await h.boot(quiet=True)
    logging.disable(logging.NOTSET)
    logging.getLogger().setLevel(logging.ERROR)
    guild = await h.setup_world(bot)
    for command in ("+level", "+balance", "+daily", "+warn <@%d> test" % h.TARGET_ID, "+stats", "+help"):
        try:
            await asyncio.wait_for(h.run_prefix(bot, guild, command), 15)
        except Exception as exc:  # noqa: BLE001
            ERRORS.append(f"{command}: {type(exc).__name__}: {exc}")
    await h.settle(idle=0.5, maximum=5)
    counts = Counter(e.split("\n")[0][:220] for e in ERRORS)
    print(f"\nschéma {os.environ['SENTRIX_PG_SCHEMA']} — {len(ERRORS)} erreur(s), {len(counts)} distincte(s)")
    for text, n in counts.most_common(60):
        print(f"{n:4d}  {text}")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(main())
