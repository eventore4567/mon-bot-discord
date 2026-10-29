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

    # 1 — +help : l'avis est un message À PART, l'aide ne le contient plus.
    envois = await lancer(bot, guild, "+help")
    trouves = avis_dans(envois)
    check(len(trouves) == 1, "+help : un avis de retrait, une seule fois", str([str(j.get("content"))[:80] for j in envois]))
    aide = [js for js in envois if js not in trouves]
    check(aide and not any(PHRASE in h.visible_text([("POST", "", js)]) for js in aide),
          "le panneau d'aide ne contient plus l'avertissement")
    if trouves:
        js = trouves[0]
        check(js["content"] == f"**<@{h.ADMIN_ID}> {PHRASE}. Nous te conseillons de passer aux commandes `/` dès maintenant.**",
              "texte demandé, en gras, avec la mention de la personne", js["content"])
        check(not js.get("components") and not js.get("embeds") and not js.get("flags"),
              "texte simple : ni embed ni Components V2", str(js)[:200])
        am = js.get("allowed_mentions") or {}
        check([str(u) for u in am.get("users") or []] == [str(h.ADMIN_ID)] and not am.get("parse") and not am.get("roles"),
              "seule la personne concernée est mentionnée", str(am))
        check("novembre" not in js["content"] and "<t:" not in js["content"], "aucune date de retrait fixée")

    # 2 — +setup juste après : pas de second rappel (écart minimum, pas de doublon).
    envois = await lancer(bot, guild, "+setup")
    check(not avis_dans(envois), "+setup juste après : pas de rappel en double")

    # 3 — Une heure plus tard : second rappel du jour, puis plus rien.
    jour = avis.jour(__import__("time").time())
    await bot.db.execute("UPDATE sentrix_prefix_notices SET last_at=last_at-? WHERE user_id=? AND day=?",
                         (avis.ECART_MIN_S, h.ADMIN_ID, jour))
    envois = await lancer(bot, guild, "+ping")
    check(len(avis_dans(envois)) == 1, "une heure plus tard : second rappel du jour")
    await bot.db.execute("UPDATE sentrix_prefix_notices SET last_at=last_at-? WHERE user_id=? AND day=?",
                         (avis.ECART_MIN_S, h.ADMIN_ID, jour))
    envois = await lancer(bot, guild, "+help")
    check(not avis_dans(envois), "troisième commande du jour : plus de rappel (2 par jour au plus)")
    row = await bot.db.fetchone("SELECT count FROM sentrix_prefix_notices WHERE user_id=? AND day=?", (h.ADMIN_ID, jour))
    check(row is not None and int(row["count"]) == 2, "le compteur est en base (gardé après redémarrage)", str(dict(row) if row else None))

    # 4 — Une ancienne commande supprimée tapée en « + » déclenche aussi l'avis.
    envois = await lancer(bot, guild, "+market", uid=h.TARGET_ID)
    check(len(avis_dans(envois)) == 1, "ancienne commande +market : l'avis part aussi")

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
