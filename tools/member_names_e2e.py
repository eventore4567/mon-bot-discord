#!/usr/bin/env python3
"""Désigner un membre comme on le tape vraiment, sur le bot booté.

Capture d'un admin (10/10/2026) puis mesure : « @nom » tapé à la main et un nom
avec une autre casse échouaient ; une mention d'un absent disait « Indiquez une
mention ». Chaque façon naturelle de désigner un membre doit marcher, et un
nom porté par plusieurs membres ne doit jamais être deviné.

    python3 tools/member_names_e2e.py
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

import discord  # noqa: E402
import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402

ADMIN = dict(author_id=h.ADMIN_ID, author_roles=(h.ADMIN_ROLE_ID,))


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)

    async def run(command: str) -> str:
        since = len(h.CALLS)
        await asyncio.wait_for(h.run_prefix(bot, guild, command, **ADMIN), 15)
        await h.settle(idle=0.3, maximum=2)
        return h.visible_text(h.CALLS[since:])

    for variant in (f"<@{h.TARGET_ID}>", str(h.TARGET_ID), "cible", "@cible", "CIBLE", "@Cible"):
        shown = await run(f"+userinfo {variant}")
        check(f"`{h.TARGET_ID}`" in shown and "introuvable" not in shown.lower() and "erreur" not in shown.lower(),
              f"+userinfo {variant} trouve le membre", shown[:120])

    # Deux membres au même surnom : pas de devinette.
    for uid in (h.TARGET_ID, h.SECOND_ID):
        member = guild.get_member(uid)
        member.nick = "Jumeau"
    shown = await run("+userinfo jumeau")
    check("Plusieurs membres" in shown and f"`{h.TARGET_ID}`" not in shown,
          "un surnom porté par deux membres : le bot demande une mention", shown[:160])
    shown = await run("+userinfo personne-inconnue")
    check("introuvable" in shown.lower() and "erreur technique" not in shown.lower(),
          "un nom inconnu : « Membre introuvable », pas une erreur technique", shown[:160])

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
