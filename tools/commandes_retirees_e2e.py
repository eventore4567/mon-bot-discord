#!/usr/bin/env python3
"""Les commandes de utils/unused_commands.SUPPRIMEES ont disparu, et rien d'autre.

28/10/2026 (Jayden) : supprimer au moins 50 commandes au lieu d'en ajouter.

    python3 tools/commandes_retirees_e2e.py
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
#: Voisines qui doivent survivre (même cog ou même famille que des retirées).
GARDEES = ("invites", "invite-leaderboard", "pay", "rob", "gamble", "memory", "minesweeper",
           "ghost", "zombie", "mining", "sentrixpro", "ban", "kick", "warn", "ticket", "help", "setup")


def check(ok: bool, label: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), label))
    print(("OK   " if ok else "ÉCHEC ") + label + (f" — {detail}" if detail and not ok else ""))


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    from cogs import commandes_retirees
    from utils.unused_commands import MASQUEES, SUPPRIMEES

    commandes_retirees.retirer(bot)  # seconde passe (le harnais n'émet pas READY)
    check(len(SUPPRIMEES) >= 50, f"au moins 50 commandes supprimées ({len(SUPPRIMEES)})")
    check(SUPPRIMEES <= MASQUEES, "toutes viennent des commandes jamais utilisées et déjà masquées")
    encore = [n for n in SUPPRIMEES if (c := bot.get_command(n)) is not None and c.qualified_name == n]
    check(not encore, "aucune commande supprimée n'est encore chargée", str(encore[:8]))
    from utils.unused_commands import OUTILS_PROPRIETAIRE_RETIRES
    restants = [n for n in OUTILS_PROPRIETAIRE_RETIRES if (c := bot.get_command(n)) is not None and c.qualified_name == n]
    check(not restants, "les outils du propriétaire global sont retirés (29/10/2026)", str(restants))
    check(any(getattr(chk, "__name__", "") == "global_blacklist_check" for chk in bot._checks),
          "la liste noire globale reste appliquée sans ses commandes")
    perdues = [n for n in GARDEES if bot.get_command(n) is None]
    check(not perdues, "les commandes voisines sont toujours là", str(perdues))

    since = len(h.CALLS)
    await asyncio.wait_for(h.run_prefix(bot, guild, "+market", author_id=h.ADMIN_ID,
                                        author_roles=(h.ADMIN_ROLE_ID,)), 20)
    await h.settle(idle=0.3, maximum=2)
    check(not any(m == "POST" and "/messages" in p for m, p, _ in h.CALLS[since:]),
          "+market ne répond plus (commande inconnue, ignorée en silence)")

    v79 = sys.modules["cogs.help_complete_v79"]
    visibles = {e.key for e in v79._catalog(bot)}
    check(not (visibles & SUPPRIMEES), "l'aide ne liste aucune commande supprimée", str(sorted(visibles & SUPPRIMEES)[:6]))

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
