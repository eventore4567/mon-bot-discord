#!/usr/bin/env python3
"""AFK sur le bot booté comme en production : posé, annoncé, survit au redémarrage, retiré.

    python3 tools/afk_e2e.py
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

MEMBRE = dict(author_id=h.TARGET_ID, author_roles=(h.MEMBER_ROLE_ID,))
AUTRE = dict(author_id=h.SECOND_ID, author_roles=(h.MEMBER_ROLE_ID,))


async def say(bot, guild, content: str, who: dict) -> str:
    since = len(h.CALLS)
    # Le vrai chemin : l'événement message, qui déclenche À LA FOIS la commande
    # et les écouteurs on_message — c'est là que +afk pouvait se retirer lui-même.
    bot.dispatch("message", h.build_message(bot, guild, content, **who))
    await h.settle(idle=0.6, maximum=4)
    return h.visible_text(h.CALLS[since:])


async def rows(bot):
    return [dict(r) for r in await bot.db.fetchall("SELECT guild_id, user_id, reason FROM afk_status")]


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    target = f"<@{h.TARGET_ID}>"

    shown = await say(bot, guild, "+afk réunion", MEMBRE)
    check("AFK" in shown and "De retour" not in shown, "+afk pose l'AFK sans le retirer aussitôt", shown[:160])
    check(await rows(bot) == [{"guild_id": h.GID, "user_id": h.TARGET_ID, "reason": "réunion"}],
          "l'AFK est enregistré en base pour CE serveur", str(await rows(bot)))

    shown = await say(bot, guild, f"tu es là {target} ?", AUTRE)
    check("est AFK depuis <t:" in shown and "réunion" in shown, "une mention annonce l'absence, la raison et depuis quand", shown[:160])

    # Redémarrage : la mémoire du cog repart de zéro, la base fait foi.
    cog = bot.get_cog("Utility")
    cog.afk_users.clear()
    cog._afk_loaded = False
    shown = await say(bot, guild, f"{target} toujours absent ?", AUTRE)
    check("réunion" in shown, "après un redémarrage, l'AFK est toujours connu", shown[:160])

    await asyncio.sleep(1.1)  # un message de la seconde suivante : le vrai retour
    shown = await say(bot, guild, "me revoilà", MEMBRE)
    check("De retour" in shown, "parler retire l'AFK et le dit", shown[:160])
    check(await rows(bot) == [], "la ligne AFK est supprimée de la base")
    shown = await say(bot, guild, f"{target} ?", AUTRE)
    check("AFK" not in shown, "plus d'annonce après le retour", shown[:160])

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
