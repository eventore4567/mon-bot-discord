#!/usr/bin/env python3
"""Anti-nuke sur le bot booté : la protection s'exécute sur le VRAI chemin.

22/11/2026. Cinq modules remplaçaient AutoMod.punish_nuker ; la protection
(liste blanche revérifiée, propriétaire du bot) enveloppait la classe APRÈS que
les couches d'instance avaient capturé la méthode : sur le bot booté, un compte
de la liste blanche qui atteignait punish_nuker était banni.

    python3 tools/anti_nuke_exempt_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    automod = bot.get_cog("Automod")

    check("punish_nuker" not in vars(automod) and type(automod).punish_nuker.__module__ == "cogs.automod",
          "punish_nuker n'est remplacée par aucun module (ni instance, ni classe)",
          f"{type(automod).punish_nuker.__module__}.{type(automod).punish_nuker.__qualname__}")

    async def exempte(self, guild, actor):
        return True

    reel = automod.is_antinuke_exempt
    automod.is_antinuke_exempt = types.MethodType(exempte, automod)
    since = len(h.CALLS)
    await asyncio.wait_for(automod.punish_nuker(guild, h.TARGET_ID, "Suppression massive de salons"), 20)
    await h.settle(idle=0.5, maximum=4)
    bans = [p for m, p, _ in h.CALLS[since:] if m == "PUT" and "/bans/" in p]
    check(not bans, "un compte de la liste blanche anti-nuke n'est pas banni", str(bans))
    automod.is_antinuke_exempt = reel

    async def illisible(self, guild, actor):
        raise RuntimeError("base indisponible")

    automod.is_antinuke_exempt = types.MethodType(illisible, automod)
    since = len(h.CALLS)
    await asyncio.wait_for(automod.punish_nuker(guild, h.TARGET_ID, "Suppression massive de salons"), 20)
    await h.settle(idle=0.5, maximum=4)
    bans = [p for m, p, _ in h.CALLS[since:] if m == "PUT" and "/bans/" in p]
    check(not bans, "une liste blanche illisible bloque le ban (irréversible)", str(bans))
    automod.is_antinuke_exempt = reel

    async def pas_exempte(self, guild, actor):
        return False

    automod.is_antinuke_exempt = types.MethodType(pas_exempte, automod)
    since = len(h.CALLS)
    await asyncio.wait_for(automod.punish_nuker(guild, h.TARGET_ID, "Suppression massive de salons"), 20)
    await h.settle(idle=0.5, maximum=4)
    bans = [p for m, p, _ in h.CALLS[since:] if m == "PUT" and "/bans/" in p]
    check(bans == [f"/guilds/{h.GID}/bans/{h.TARGET_ID}"], "un vrai nuker est banni", str(bans))

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
