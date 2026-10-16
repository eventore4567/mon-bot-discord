#!/usr/bin/env python3
"""Comment les commandes « / » répondent, sur le bot booté : directement, ou par
« SentriX réfléchit… » (defer) puis une modification.

Un defer immédiat affiche « réfléchit… » même quand la réponse est instantanée,
et coûte un aller-retour Discord de plus avant que l'utilisateur voie quoi que
ce soit. Discord laisse 3 s pour répondre ; seule une commande lente en a besoin.

    python3 tools/slash_response_probe.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import sentrix_e2e_harness as h  # noqa: E402

LATENCY = 0.08  # aller-retour Discord typique

SPECS = [
    "help", "ping", "levels rank", "economy balance", "server info", "server members",
    "user info", "economy daily", "user avatar",
]


async def main() -> int:
    import discord

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    original = discord.http.HTTPClient.request

    async def request(self, route, **kwargs):
        await asyncio.sleep(LATENCY)
        return await original(self, route, **kwargs)

    discord.http.HTTPClient.request = request
    rows = []
    for spec in SPECS:
        since = len(h.CALLS)
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(h.run_slash(bot, guild, spec), 20)
        except Exception as exc:  # noqa: BLE001
            rows.append((spec, f"erreur {type(exc).__name__}", 0, 0))
            continue
        await h.settle(idle=0.3, maximum=3)
        first_visible = None
        kinds = []
        for method, path, js in h.CALLS[since:]:
            if path.endswith("/callback"):
                kinds.append({4: "réponse", 5: "réfléchit…", 6: "maj", 9: "modal"}.get((js or {}).get("type"), "?"))
        calls = sum(1 for _m, p, _j in h.CALLS[since:] if "/interactions/" in p or "/webhooks/" in p)
        rows.append((spec, " → ".join(kinds) or "aucune", calls, round((time.monotonic() - t0) * 1000)))
    print(f"\n{'commande':32s} {'réponse':28s} appels  ms")
    for spec, kind, calls, ms in rows:
        print(f"{spec:32s} {kind:28s} {calls:5d}  {ms}")
    deferred = sum(1 for r in rows if "réfléchit" in r[1])
    print(f"\n« réfléchit… » affiché : {deferred}/{len(rows)} commandes")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(main())
