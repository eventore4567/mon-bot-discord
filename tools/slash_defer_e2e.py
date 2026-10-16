#!/usr/bin/env python3
"""Réponses des commandes « / » sur le bot booté : rapides sans « réfléchit… »,
lentes avec, silencieuses refermées, erreurs visibles.

Avant le 16/10/2026, chaque commande « / » commençait par « SentriX réfléchit… »
(defer immédiat), même quand la réponse était instantanée.

    python3 tools/slash_defer_e2e.py
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

import discord  # noqa: E402
from discord.ext import commands  # noqa: E402

import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402


def responses(since: int) -> list[tuple[float, int]]:
    return [(t, (js or {}).get("type")) for t, (m, p, js) in zip(TIMES[since:], h.CALLS[since:])
            if p.endswith("/callback")]


TIMES: list[float] = []


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    original = discord.http.HTTPClient.request

    async def timed(self, route, **kwargs):
        result = await original(self, route, **kwargs)
        TIMES.extend([time.monotonic()] * (len(h.CALLS) - len(TIMES)))
        return result

    discord.http.HTTPClient.request = timed

    async def slash(spec: str):
        since = len(h.CALLS)
        t0 = time.monotonic()
        await asyncio.wait_for(h.run_slash(bot, guild, spec), 20)
        await h.settle(idle=0.3, maximum=3)
        TIMES.extend([time.monotonic()] * (len(h.CALLS) - len(TIMES)))
        return since, t0

    # 1. Rapides : une seule réponse directe.
    for spec in ("help", "ping", "economy balance", "server info"):
        since, _t0 = await slash(spec)
        kinds = [k for _t, k in responses(since)]
        check(kinds == [4], f"/{spec} répond directement, sans « réfléchit… »", str(kinds))

    ping = bot.get_command("ping")
    original_callback = ping._callback

    # 2. Lente : « réfléchit… » apparaît avant la limite de 3 s de Discord, puis la réponse.
    async def lente(self, ctx, *args, **kwargs):
        await asyncio.sleep(2.3)
        return await original_callback(self, ctx, *args, **kwargs)

    ping._callback = lente
    since, t0 = await slash("ping")
    rep = responses(since)
    check(rep and rep[0][1] == 5 and rep[0][0] - t0 < 2.9,
          "commande lente : « réfléchit… » avant 3 s", str([(round(t - t0, 2), k) for t, k in rep]))
    shown = h.visible_text(h.CALLS[since:])
    check("ms" in shown.lower() or "latence" in shown.lower() or len(shown) > 10,
          "puis la vraie réponse remplace l'attente", shown[:160])

    # 3. Silencieuse : écrit dans le salon sans répondre à Discord.
    async def silencieuse(self, ctx, *args, **kwargs):
        await ctx.channel.send("message direct")

    ping._callback = silencieuse
    since, _t0 = await slash("ping")
    kinds = [k for _t, k in responses(since)]
    flags = [(js or {}).get("data", {}).get("flags") for _m, p, js in h.CALLS[since:] if p.endswith("/callback")]
    check(kinds == [4] and len(flags) == 1 and int(flags[0] or 0) & 64, "commande silencieuse : courte confirmation éphémère, pas de « réfléchit… »",
          f"{kinds} {flags}")

    # 3 bis. Lente ET silencieuse : le « réfléchit… » du minuteur est refermé.
    async def lente_silencieuse(self, ctx, *args, **kwargs):
        await asyncio.sleep(2.1)
        await ctx.channel.send("message direct")

    ping._callback = lente_silencieuse
    since, _t0 = await slash("ping")
    kinds = [k for _t, k in responses(since)]
    closed = [(m, js) for m, p, js in h.CALLS[since:] if p.endswith("/messages/@original")
              and (m == "DELETE" or (m == "PATCH" and (js or {}).get("content")))]
    check(kinds == [5] and closed, "lente et silencieuse : « réfléchit… » refermé, jamais laissé vide",
          f"{kinds} {closed[:1]}")

    # 4. Erreur : visible, jamais une interaction sans réponse.
    async def en_erreur(self, ctx, *args, **kwargs):
        raise commands.BadArgument("valeur refusée pour le test")

    ping._callback = en_erreur
    since, _t0 = await slash("ping")
    kinds = [k for _t, k in responses(since)]
    shown = h.visible_text(h.CALLS[since:])
    check(kinds and len(shown.strip()) > 0, "une erreur reste visible", f"{kinds} {shown[:120]}")
    ping._callback = original_callback

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException:
        import traceback

        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)
