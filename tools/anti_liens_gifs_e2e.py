#!/usr/bin/env python3
"""Anti-liens « sauf GIFs » choisi dans Réglages avancés (27/11/2026).

    python3 tools/anti_liens_gifs_e2e.py
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

import discord  # noqa: E402
import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402
from welcome_e2e import admin_interaction  # noqa: E402

GIF = "regarde https://tenor.com/view/chat-drole-123456"
AUTRE = "regarde https://site-random.example/page"


async def main() -> int:
    from cogs import setup_v2_ui
    from cogs import setup_experience_v74 as v74

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    await bot.db.set_automod(h.GID, "antilink", 1)
    automod = bot.get_cog("Automod")
    automod.automod_cache.clear()

    async def poster(texte, auteur):
        automod.incidents.clear()
        message = h.build_message(bot, guild, texte, author_id=auteur, author_name="membre")
        debut = len(h.CALLS)
        await automod.on_message(message)
        await h.settle(idle=0.6, maximum=4)
        return any(m == "DELETE" and p.endswith(f"/messages/{message.id}") for m, p, _ in h.CALLS[debut:]) or any(
            p.endswith("bulk-delete") and str(message.id) in map(str, (js or {}).get("messages", []))
            for m, p, js in h.CALLS[debut:])

    check(await poster(GIF, 100000000000000601), "par défaut, un lien GIF est supprimé (tous les liens bloqués)")

    owner = v74.SentriXSetupV74(bot, guild, h.ADMIN_ID)
    await owner.prepare()
    panneau = await setup_v2_ui._security_policy_setup_panel(owner, h.ADMIN_ID, "antilink")
    vue = panneau.view if hasattr(panneau, "view") else panneau
    menus = [i for i in getattr(vue, "children", []) if isinstance(i, discord.ui.Select) and i.placeholder == "Liens autorisés"]
    if not menus:
        menus = [i for i in getattr(panneau, "walk_children", lambda: [])() if isinstance(i, discord.ui.Select)
                 and i.placeholder == "Liens autorisés"]
    check(bool(menus), "Réglages avancés → Anti-liens propose « Liens autorisés »")
    if menus:
        menus[0]._values = ["1"]
        try:
            await menus[0].callback(admin_interaction(bot))
        except Exception:  # noqa: BLE001 — rafraîchissement non testé
            pass
    reglage = await bot.db.get_automod(h.GID)
    check(int(reglage["antilink_gifs"] or 0) == 1, "le choix « Laisser passer les GIFs » est enregistré")

    check(not await poster(GIF, 100000000000000602), "mode GIFs : un lien Tenor passe")
    check(await poster(AUTRE, 100000000000000603), "mode GIFs : un autre lien est toujours supprimé")
    check(await poster(GIF + " et https://site-random.example", 100000000000000604),
          "mode GIFs : un GIF accompagné d'un autre lien est supprimé")

    # Revue Codex (PR #735) : le vrai hôte, pas ce qui suit un « @ » de la requête.
    for piege in ("https://evil.com?@tenor.com", "https://evil.com#@giphy.com", "https://tenor.com.evil.com/x",
                  "https://t\u0435nor.com/view/123", "https://g\u00edphy.com/page", "https://evil.com\\@tenor.com"):
        check(await poster(f"clique {piege}", 100000000000000610 + len(piege)),
              f"mode GIFs : « {piege} » (pas un vrai GIF) est supprimé")

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
