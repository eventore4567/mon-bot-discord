#!/usr/bin/env python3
"""Réponses complètes, sur le bot booté : le résultat ET la suite, pas une ligne sèche.

Avant le 22/10/2026 : « 10 🪙 déposés en banque. », « +50 pièces · série 1 j. »,
« Article introuvable. », « Annonce indisponible. » — ni solde, ni rendez-vous,
ni commande pour s'en sortir.

    python3 tools/rich_responses_e2e.py
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

ADMIN = dict(author_id=h.ADMIN_ID, author_roles=(h.ADMIN_ROLE_ID,))


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    await bot.db.add_balance(h.GID, h.ADMIN_ID, 500)

    async def say(text: str) -> str:
        since = len(h.CALLS)
        await asyncio.wait_for(h.run_prefix(bot, guild, text, **ADMIN), 20)
        await h.settle(idle=0.3, maximum=3)
        return re.sub(r"\s+", " ", h.visible_text(h.CALLS[since:]))

    t = await say("+deposit 100")
    check("Portefeuille : **400**" in t and "Banque : **100**" in t and "Total : **500**" in t,
          "dépôt : les soldes qui en résultent", t[:200])
    t = await say("+withdraw 40")
    check("Portefeuille : **440**" in t and "Banque : **60**" in t, "retrait : les soldes qui en résultent", t[:200])
    t = await say("+deposit 99999")
    check("Portefeuille : **440**" in t and "all" in t, "montant refusé : ce que le membre possède vraiment", t[:200])
    t = await say("+checkin")
    check("**+50**" in t and "Jours de série : **1**" in t and "<t:" in t and "**+60**" in t,
          "check-in : gain, série et rendez-vous de demain avec son gain", t[:240])
    t = await say("+checkin")
    check("Déjà récupéré" in t and "<t:" in t, "check-in déjà fait : quand revenir", t[:200])
    t = await say("+buy 999")
    check("n°999" in t and "+shop" in t, "article inconnu : la commande qui liste les articles", t[:200])
    t = await say("+mbuy 999")
    check("n°999" in t and "+market" in t, "annonce indisponible : pourquoi et où regarder", t[:200])
    t = await say("+joinevent inconnu")
    check("+event-list" in t, "événement introuvable : la liste des noms exacts", t[:200])
    t = await say("+afk pause café")
    check("pause café" in t and "prochain message" in t, "AFK : comment le statut se retire", t[:220])

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
