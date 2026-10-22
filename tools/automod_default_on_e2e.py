#!/usr/bin/env python3
"""Auto Mode sur un serveur qui n'a jamais touché à l'interrupteur « Sécurité ».

Le 22/10/2026, « module absent = inactif » appliqué à ``security`` avait éteint
l'anti-spam partout : 240 messages de spam restaient affichés, aucun spammeur
n'était traité. Les protections sont actives tant qu'on ne les coupe pas.

    python3 tools/automod_default_on_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import spam_burst_e2e  # noqa: E402

if __name__ == "__main__":
    try:
        asyncio.run(spam_burst_e2e.main(20, 12, sans_ligne_module=True))
    except BaseException:
        import traceback

        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)
