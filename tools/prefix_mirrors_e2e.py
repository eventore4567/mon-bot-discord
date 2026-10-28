#!/usr/bin/env python3
"""+logs, +role, +queue, +nowplaying relaient vers les commandes + existantes.

28/10/2026 : « +logs » et « +role » ne répondaient rien alors que /logs et /role
existent. Le relais doit donner EXACTEMENT la réponse de la commande cible, y
compris son refus pour un simple membre (même décision de permission).

    python3 tools/prefix_mirrors_e2e.py
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

RESULTS: list[tuple[bool, str]] = []
ADMIN = {"author_id": h.ADMIN_ID, "author_roles": (h.ADMIN_ROLE_ID,)}
MEMBRE = {"author_id": h.TARGET_ID, "author_roles": (h.MEMBER_ROLE_ID,)}


def check(ok: bool, label: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), label))
    print(("OK   " if ok else "ÉCHEC ") + label + (f" — {detail}" if detail and not ok else ""))


async def run(bot, guild, texte: str, qui: dict):
    since = len(h.CALLS)
    await asyncio.wait_for(h.run_prefix(bot, guild, texte, **qui), 20)
    await h.settle(idle=0.4, maximum=4)
    calls = h.CALLS[since:]
    # La référence SX- et l'horodatage changent d'un appel à l'autre.
    texte_vu = re.sub(r"SX-[A-Z0-9-]+|<t:\d+(:\w)?>", "", h.visible_text(calls))
    return calls, re.sub(r"\s+", " ", texte_vu).strip()


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    bot.get_cog("PrefixSlashMirrors")._installer()  # seconde passe (le harnais n'émet pas READY)
    check(bot.get_command("logs search") is not None and bot.get_command("role give") is not None,
          "+logs et +role existent après démarrage")

    role = f"<@&{h.MEMBER_ROLE_ID}>"
    _c, direct = await run(bot, guild, f"+info role {role}", ADMIN)
    _c, relais = await run(bot, guild, f"+role info {role}", ADMIN)
    check(bool(relais) and relais == direct, "+role info = +info role (même réponse)", f"{relais[:120]} ≠ {direct[:120]}")

    _c, refus_direct = await run(bot, guild, f"+giverole <@{h.TARGET_ID}> {role}", MEMBRE)
    calls, refus_relais = await run(bot, guild, f"+role give <@{h.TARGET_ID}> {role}", MEMBRE)
    check(bool(refus_relais) and refus_relais == refus_direct, "membre : +role give refusé exactement comme +giverole",
          f"{refus_relais[:120]} ≠ {refus_direct[:120]}")
    check(not any(m == "PUT" and "/roles/" in p for m, p, _ in calls), "membre : aucun rôle attribué")

    calls, _t = await run(bot, guild, f"+role give <@{h.TARGET_ID}> <@&{h.PING_ROLE_ID}>", ADMIN)
    check(any(m == "PUT" and p.endswith(f"/members/{h.TARGET_ID}/roles/{h.PING_ROLE_ID}") for m, p, _ in calls),
          "admin : +role give attribue le rôle", str([(m, p) for m, p, _ in calls])[:200])

    _c, q = await run(bot, guild, "+queue", ADMIN)
    check("File d’attente" in q or "File d'attente" in q, "+queue = +music queue", q[:120])
    _c, aide = await run(bot, guild, "+logs", ADMIN)
    check("+logs search" in aide, "+logs seul liste ses sous-commandes", aide[:120])

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except BaseException:
        import traceback
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)
