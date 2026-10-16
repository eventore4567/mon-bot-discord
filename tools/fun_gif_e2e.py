#!/usr/bin/env python3
"""Le GIF des commandes Fun correspond au résultat affiché, sur le bot booté.

Avant le 16/10/2026, +ship montrait deux mains enlacées même à 3 %, +mood un grand
sourire même à 8 %, et +cheer une personne joyeuse au lieu d'un encouragement.

    python3 tools/fun_gif_e2e.py
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
    fun = sys.modules["cogs.fun_social"]
    asked: list[str] = []

    async def fake_gif(category):  # le harnais coupe Internet : on capture la catégorie
        asked.append(category)
        return f"https://nekos.best/api/v2/{category}/demo.gif", "Démo"

    fun.fetch_gif = fake_gif

    async def run(text: str):
        since = len(h.CALLS)
        del asked[:]
        await asyncio.wait_for(h.run_prefix(bot, guild, text, **ADMIN), 15)
        await h.settle(idle=0.3, maximum=3)
        await asyncio.sleep(4.1)  # anti-spam Fun : 4 s entre deux actions
        raw = str([js for _m, _p, js in h.CALLS[since:]])
        return h.visible_text(h.CALLS[since:]), raw

    for mode, motif in (("ship", r"Compatibilité du jour : \*\*(\d+) %"),
                        ("mood", r"Bonne humeur : (\d+)%"),
                        ("luck", r"Chance : (\d+)%"),
                        ("rizz", r"Charisme : (\d+)%")):
        commande = "+ship" if mode == "ship" else f"+fun {mode}"  # ship a un raccourci, pas les autres
        shown, raw = await run(f"{commande} <@{h.TARGET_ID}>")
        m = re.search(motif, shown)
        score = int(m.group(1)) if m else None
        attendu = fun.gif_selon_score(mode, score) if score is not None else None
        check(score is not None and asked == [attendu] and f"/{attendu}/demo.gif" in raw,
              f"+{mode} : le GIF suit le score affiché ({score} → {attendu})", f"{asked} {shown[:120]}")

    shown, raw = await run(f"+fun cheer <@{h.TARGET_ID}>")
    check(asked == ["thumbsup"] and "/thumbsup/demo.gif" in raw, "+fun cheer montre un geste d'encouragement",
          str(asked))

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
