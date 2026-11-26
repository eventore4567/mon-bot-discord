#!/usr/bin/env python3
"""Anti-pub : une offre de produit illégal est supprimée (26/11/2026).

    python3 tools/anti_illicite_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    sys.modules["cogs.automod"].INCIDENT_LOG_DELAY_SECONDS = 0.2
    await bot.db.execute("INSERT INTO automod_settings (guild_id) VALUES (?) ON CONFLICT(guild_id) DO NOTHING", (h.GID,))
    await bot.db.execute("UPDATE automod_settings SET antiscam=1 WHERE guild_id=?", (h.GID,))
    bot.get_cog("Automod").automod_cache.clear()

    async def poster(texte, auteur):
        message = h.build_message(bot, guild, texte, author_id=auteur, author_name="membre")
        debut = len(h.CALLS)
        bot.dispatch("message", message)
        await h.settle(idle=1.0, maximum=6)
        supprime = any(m == "DELETE" and re.fullmatch(rf"/channels/{h.CID}/messages/{message.id}", p)
                       for m, p, _ in h.CALLS[debut:])
        return supprime, h.visible_text(h.CALLS[debut:])

    supprime, texte = await poster("je vends de la coke, dm moi", h.TARGET_ID)
    check(supprime, "une offre de drogue est supprimée")
    check("vente illicite" in texte or "illicite" in texte.casefold(),
          "le motif « vente illicite » apparaît (log ou avertissement)", texte[-300:])
    supprime, _ = await poster("la coke dans le film scarface c'est culte", h.SECOND_ID)
    check(not supprime, "une simple mention dans un film n'est pas supprimée")

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
