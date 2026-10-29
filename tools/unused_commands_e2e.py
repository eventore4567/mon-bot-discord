#!/usr/bin/env python3
"""Commandes masquées faute d'usage (utils/unused_commands.py), sur le bot booté.

16/10/2026 : hors de l'aide et du menu « / », utilisables en préfixe.
28/10/2026 : passage à 100 % « / » ; les masquées gardées reviennent dans le
menu avec les mêmes contrôles. Seules les supprimées restent dehors.

    python3 tools/unused_commands_e2e.py
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


def slash_paths(bot) -> set[str]:
    out = set()

    def walk(node, parent=""):
        name = f"{parent} {node.name}".strip()
        kids = list(getattr(node, "commands", ()) or ())
        if not kids:
            out.add(name)
        for k in kids:
            walk(k, name)

    for node in bot.tree.get_commands(type=discord.AppCommandType.chat_input):
        walk(node)
    return out


async def main() -> int:
    from utils import slash_catalog, unused_commands

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    helpmod = sys.modules["cogs.help"]

    async def prefix(text: str, **who) -> str:
        since = len(h.CALLS)
        await asyncio.wait_for(h.run_prefix(bot, guild, text, **(who or ADMIN)), 15)
        await h.settle(idle=0.3, maximum=3)
        return h.visible_text(h.CALLS[since:])

    # L'aide SERVIE est help_complete_v79 (elle remplace OfficialHelp.send_help) ;
    # cogs/help._visible n'est que l'ancienne.
    v79 = sys.modules["cogs.help_complete_v79"]
    visibles = {e.key for e in v79._catalog(bot)} | {c.qualified_name for c in helpmod._visible(bot)}
    accueil = await prefix("+help")
    check("jamais utilisées" not in accueil and "535 commandes uniques" not in accueil,
          "l'accueil de l'aide ne renvoie plus vers des commandes « + » masquées", accueil[:300])
    hors_menu = {n for n in unused_commands.MASQUEES if unused_commands.masquee(n)}
    check(not (visibles & hors_menu), "l'aide ne liste aucune commande supprimée",
          str(sorted(visibles & hors_menu)[:5]))
    for revenue in ("pay", "buy", "shoprole add", "minesweeper"):
        check(revenue in visibles, f"« {revenue} » est revenue dans l'aide")
    for garde in ("ban", "hackban", "tempban", "quarantine", "music skip", "giveaway end", "setup"):
        check(garde in visibles, f"« {garde} » reste dans l'aide")

    paths = slash_paths(bot)
    masked_paths = {e.path for e in slash_catalog._MASQUEES_DU_MENU}
    check(not (paths & masked_paths) and "market view" not in paths and "ban" in paths,
          f"le menu « / » ne publie plus les {len(masked_paths)} chemins masqués", str(sorted(paths & masked_paths)[:5]))
    check({"economy pay", "shop buy", "shop role-add", "puzzle minesweeper"} <= paths,
          "les masquées gardées sont publiées en « / »", str(sorted({"economy pay", "shop buy", "shop role-add", "puzzle minesweeper"} - paths)))

    # Les SUPPRIMEES (28/10/2026) ont quitté le bot ; les autres masquées restent en +.
    from cogs import commandes_retirees
    commandes_retirees.retirer(bot)
    supprimees = unused_commands.SUPPRIMEES
    for nom in unused_commands.MASQUEES - supprimees:
        if nom.split(" ")[0] in supprimees:
            continue  # sous-commande d'une racine supprimée (logevent on/off)
        if bot.get_command(nom) is None:
            check(False, f"+{nom} existe toujours")
            break
    else:
        check(True, f"les {len(unused_commands.MASQUEES)} commandes masquées existent toujours en préfixe")

    # « market » a été supprimée le 28/10/2026 : l'exemple est une masquée gardée.
    shown = await prefix("+help minesweeper")
    check("minesweeper" in shown.lower() and "Recherche" not in shown, "« +help minesweeper » montre toujours la fiche",
          shown[:160])
    shown = await prefix("+minesweeper")
    check(len(shown.strip()) > 0 and "introuvable" not in shown.lower(), "« +minesweeper » fonctionne toujours",
          shown[:160])
    # Même décision de permission qu'avant : un membre sans droit reste refusé.
    shown = await prefix("+reset-economy", author_id=h.TARGET_ID, author_roles=())
    check(any(w in shown.lower() for w in ("permission", "accès", "réservée", "autoris")),
          "« +reset-economy » reste refusé à un simple membre", shown[:160])

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
