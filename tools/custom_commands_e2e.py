#!/usr/bin/env python3
"""Commandes personnalisées à actions (cogs/custom_commands), sur le bot booté.

    python3 tools/custom_commands_e2e.py
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

RESULTS: list[tuple[bool, str]] = []
ADMIN = dict(author_id=h.ADMIN_ID, author_roles=(h.ADMIN_ROLE_ID,))


def check(ok: bool, label: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), label))
    print(("OK   " if ok else "ÉCHEC ") + label + (f" — {detail}" if detail and not ok else ""))


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    # Production : le « + » des commandes SentriX est coupé ; les personnalisées restent.
    os.environ["SENTRIX_PREFIXE_ACTIF"] = "0"

    async def slash(spec: str) -> str:
        since = len(h.CALLS)
        root, opts = h.slash_options_from_spec(bot, spec)
        inter = h.build_interaction(bot, root, opts, **ADMIN)
        await asyncio.wait_for(bot.tree._call(inter), 20)
        await h.settle(idle=0.4, maximum=3)
        return h.visible_text(h.CALLS[since:])

    texte = await slash("custom create nom=bonus message=Bonus_pour_{user}")
    check("Commande enregistrée" in texte and "bonus" in texte, "/custom create enregistre la commande", texte[:200])
    texte = await slash(f"custom role-add nom=bonus role={h.PING_ROLE_ID}")
    check("Action ajoutée" in texte and f"<@&{h.PING_ROLE_ID}>" in texte, "/custom role-add ajoute l'action", texte[:200])
    texte = await slash("custom money nom=bonus montant=250")
    check("Action ajoutée" in texte and "250" in texte, "/custom money ajoute l'action", texte[:200])
    await slash("custom delete-trigger etat=on")

    avant = await bot.db.fetchone("SELECT cash FROM economy WHERE guild_id=? AND user_id=?", (h.GID, h.TARGET_ID))
    avant = int(avant["cash"]) if avant else 0
    since = len(h.CALLS)
    message = h.build_message(bot, guild, "+bonus", author_id=h.TARGET_ID, author_roles=(h.MEMBER_ROLE_ID,))
    bot.dispatch("message", message)
    await h.settle(idle=0.8, maximum=5)
    appels = h.CALLS[since:]
    check(any("Bonus_pour_" in str((js or {}).get("content")) for _m, _p, js in appels if isinstance(js, dict)),
          "+bonus répond même avec le « + » des commandes SentriX coupé")
    check(any(m == "PUT" and f"/members/{h.TARGET_ID}/roles/{h.PING_ROLE_ID}" in p for m, p, _ in appels),
          "le rôle est donné à la personne")
    apres = await bot.db.fetchone("SELECT cash FROM economy WHERE guild_id=? AND user_id=?", (h.GID, h.TARGET_ID))
    check(apres is not None and int(apres["cash"]) == avant + 250, "250 ajoutés à son argent", str(dict(apres) if apres else None))
    check(any(m == "DELETE" and f"/messages/{message.id}" in p for m, p, _ in appels),
          "le message qui a lancé la commande est supprimé")

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
