#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import pathlib
import traceback

OUT = pathlib.Path(__file__).with_name(".acceptance_failure.txt")


if __name__ == "__main__":
    try:
        from tools import user_acceptance_audit
        asyncio.run(user_acceptance_audit.main_audit())
    except BaseException:
        OUT.write_text(traceback.format_exc(), encoding="utf-8")
        print(OUT.read_text(encoding="utf-8"), flush=True)
    else:
        OUT.write_text("SUCCESS\n", encoding="utf-8")
        print("SUCCESS", flush=True)
