#!/usr/bin/env python3
"""Avis de retrait des commandes « + » sur le bot booté (passage à 100 % « / »).

    SENTRIX_E2E_AVIS_PREFIXE=1 python3 tools/prefix_deprecation_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

os.environ["SENTRIX_E2E_AVIS_PREFIXE"] = "1"
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import sentrix_e2e_harness as h  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), label))
    print(("OK   " if ok else "ÉCHEC ") + label + (f" — {detail}" if detail and not ok else ""))


PHRASE = "Les commandes avec le préfixe `+` seront bientôt supprimées"


async def lancer(bot, guild, texte, uid=None):
    since = len(h.CALLS)
    uid = uid or h.ADMIN_ID
    await asyncio.wait_for(h.run_prefix(bot, guild, texte, author_id=uid, author_roles=(h.ADMIN_ROLE_ID,)), 20)
    await h.settle(idle=0.4, maximum=3)
    return [js for m, p, js in h.CALLS[since:] if m == "POST" and p == f"/channels/{h.CID}/messages" and isinstance(js, dict)]


def avis_dans(envois):
    return [js for js in envois if PHRASE in str(js.get("content") or "")]


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    from cogs import prefix_deprecation as avis
    await bot.db.execute("DELETE FROM sentrix_prefix_notices")

    # 31/10/2026 : le « + » est de nouveau actif à côté du « / ». Tant qu'il l'est,
    # aucun avis de retrait ne part : il annoncerait une suppression qui n'aura pas lieu.
    for texte, uid in (("+help", h.ADMIN_ID), ("+setup", h.ADMIN_ID), ("+ping", h.ADMIN_ID), ("+market", h.TARGET_ID)):
        envois = await lancer(bot, guild, texte, uid=uid)
        check(not avis_dans(envois), f"{texte} : aucun avis de retrait tant que le « + » est actif",
              str([str(j.get("content"))[:80] for j in envois]))
    envois = await lancer(bot, guild, "+help")
    check(bool(envois), "+help répond toujours (le « + » reste utilisable)")
    row = await bot.db.fetchone("SELECT COUNT(*) AS n FROM sentrix_prefix_notices")
    check(row is not None and int(row["n"]) == 0, "aucun rappel compté en base", str(dict(row) if row else None))

    # 4b — « + » retiré (production) : rien n'est exécuté, seul le rappel part.
    os.environ["SENTRIX_PREFIXE_ACTIF"] = "0"
    await bot.db.execute("DELETE FROM sentrix_prefix_notices")
    envois = await lancer(bot, guild, "+ping", uid=h.SECOND_ID)
    textes = [str(j.get("content") or "") + h.visible_text([("POST", "", j)]) for j in envois]
    check(len(envois) == 1 and "ont été supprimées" in textes[0] and f"<@{h.SECOND_ID}>" in textes[0]
          and "/ping" in textes[0],
          "« + » retiré : un seul message qui donne la commande / à utiliser, rien d'exécuté", str(textes)[:300])
    envois = await lancer(bot, guild, "+clear 5", uid=h.ADMIN_ID)
    textes = [str(j.get("content") or "") for j in envois]
    check(len(envois) == 1 and "/clear" in textes[0], "+clear : « Utilise /clear à la place »", str(textes)[:300])
    os.environ["SENTRIX_PREFIXE_ACTIF"] = "1"

    # 5 — Les commandes « / » ne déclenchent jamais l'avis.
    since = len(h.CALLS)
    await asyncio.wait_for(h.run_slash(bot, guild, "ping"), 15)
    await h.settle(idle=0.3, maximum=2)
    check(not any(PHRASE in str((js or {}).get("content")) for m, p, js in h.CALLS[since:] if isinstance(js, dict)),
          "/ping : aucun avis")

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
