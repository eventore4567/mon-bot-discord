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


async def lancer(bot, guild, texte):
    since = len(h.CALLS)
    await asyncio.wait_for(h.run_prefix(bot, guild, texte, author_id=h.ADMIN_ID, author_roles=(h.ADMIN_ROLE_ID,)), 20)
    await h.settle(idle=0.4, maximum=3)
    return [js for m, p, js in h.CALLS[since:] if m == "POST" and p == f"/channels/{h.CID}/messages" and isinstance(js, dict)]


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    from cogs import prefix_deprecation as avis
    avis._dernier_avis.clear()

    envois = await lancer(bot, guild, "+ping")
    avis_msgs = [js for js in envois if "seront retirées le 30 novembre 2026" in str(js.get("content") or "")]
    check(len(avis_msgs) == 1, "première commande « + » : un avis de retrait", str([str(j.get("content"))[:80] for j in envois]))
    if avis_msgs:
        js = avis_msgs[0]
        check("<t:" in js["content"] and ":R>" in js["content"], "le temps restant est un horodatage relatif Discord")
        check(not js.get("components") and not js.get("embeds"), "texte simple, pas une carte")
        check((js.get("allowed_mentions") or {}).get("parse") == [], "aucune mention")
    envois = await lancer(bot, guild, "+ping")
    check(not any("retirées" in str(j.get("content") or "") for j in envois), "même personne, même jour : pas de second avis")

    # L'aide le dit en permanence, en tête, même quand l'avis du jour est déjà parti.
    since = len(h.CALLS)
    await lancer(bot, guild, "+help")
    aide = h.visible_text(h.CALLS[since:])
    check("seront retirées le 30 novembre 2026" in aide and "Centre d'aide" in aide,
          "l'accueil de +help affiche l'avertissement de retrait", aide[:300])

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
