#!/usr/bin/env python3
"""+balance montre les derniers mouvements (25/11/2026).

L'historique (+transactions, cogs/v17_ai_economy_games) n'était plus chargé en
production depuis août. Il est relogé dans +balance, sans nouvelle commande.

    python3 tools/economie_mouvements_e2e.py
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

import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)

    async def commande(texte, auteur):
        debut = len(h.CALLS)
        await asyncio.wait_for(h.run_prefix(bot, guild, texte, author_id=auteur), 20)
        await h.settle(idle=0.4, maximum=4)
        return h.visible_text(h.CALLS[debut:])

    await commande("+daily", h.TARGET_ID)
    texte = await commande("+balance", h.TARGET_ID)
    check("Derniers mouvements" in texte, "+balance affiche les derniers mouvements", texte[-300:])
    check("+" in texte.split("Derniers mouvements", 1)[-1][:200], "le daily apparaît comme une entrée d'argent",
          texte.split("Derniers mouvements", 1)[-1][:200])

    texte = await commande(f"+balance <@{h.TARGET_ID}>", h.SECOND_ID)
    check("Derniers mouvements" not in texte, "un autre membre ne voit pas les mouvements d'autrui", texte[-200:])

    texte = await commande(f"+balance <@{h.TARGET_ID}>", h.AUTHOR_ID)
    check("Derniers mouvements" in texte, "le staff (Gérer le serveur) voit les mouvements d'un membre", texte[-200:])

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
