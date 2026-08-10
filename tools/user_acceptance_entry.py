#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import pathlib
import sys
import traceback

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def github_escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


if __name__ == "__main__":
    try:
        from tools import user_acceptance_audit
        asyncio.run(user_acceptance_audit.main_audit())
    except Exception as exc:
        traceback.print_exc()
        message = github_escape(f"{type(exc).__name__}: {exc}")[:4000]
        print(f"::error title=SentriX user acceptance::{message}", flush=True)
        raise
