#!/usr/bin/env python3
"""/setup en six sections, sur le bot booté (22/11/2026).

Accueil → section → réglage → « Retour » revient à la SECTION ; « Activer toutes
les protections » allume réellement les protections recommandées.

    python3 tools/setup_sections_e2e.py
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
from welcome_e2e import admin_interaction, control  # noqa: E402


def bouton(view, libelle):
    return control(view, lambda i: isinstance(i, discord.ui.Button) and i.label == libelle)


async def cliquer(bot, item):
    await item.callback(admin_interaction(bot))
    await h.settle(idle=0.3, maximum=3)


async def main() -> int:
    from cogs import securite_simple, setup_experience_v74 as v74

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    view = v74.SentriXSetupV74(bot, guild, h.ADMIN_ID)
    await view.prepare()
    view.clear_items()
    await view._build_home()

    noms = [s[1] for s in v74.SECTIONS]
    check(all(bouton(view, nom) is not None for nom in noms), "l'accueil propose les six sections", str(noms))
    check(control(view, lambda i: isinstance(i, discord.ui.Select)) is None,
          "l'accueil n'a plus le menu de 22 entrées")

    await cliquer(bot, bouton(view, "Modération"))
    check(view.page == "section:moderation" and bouton(view, "Ouvrir") is not None,
          "une section s'ouvre et liste ses réglages", str(view.page))

    ouvrir = [b for b in view.walk_children() if isinstance(b, discord.ui.Button) and b.label == "Ouvrir"]
    await cliquer(bot, ouvrir[0])
    check(view.page == "moderation", "« Ouvrir » mène au réglage", str(view.page))

    await cliquer(bot, bouton(view, "Retour"))
    check(view.page == "section:moderation", "« Retour » revient à la section, pas à l'accueil", str(view.page))

    await cliquer(bot, bouton(view, "Retour"))
    check(view.page is None and bouton(view, "Sécurité") is not None, "« Retour » de la section revient à l'accueil")

    avant = await securite_simple.etats(view)
    await cliquer(bot, bouton(view, "Activer toutes les protections"))
    apres = await securite_simple.etats(view)
    check(not all(avant.values()) and all(apres.values()),
          "« Activer toutes les protections » les allume toutes", f"{sum(avant.values())} → {sum(apres.values())}")
    check(bouton(view, "Toutes les protections sont actives") is not None,
          "l'accueil indique ensuite que tout est actif")

    # Revue Codex (PR #714) : tout coché, mais SentriX sans « Voir le journal
    # d'audit » ni « Expulser » — l'accueil ne doit pas annoncer « protégé ».
    from unittest.mock import PropertyMock, patch

    bridees = discord.Permissions(manage_guild=True, manage_roles=True, manage_channels=True,
                                  manage_messages=True, moderate_members=True, ban_members=True)
    with patch.object(discord.Member, "guild_permissions", new_callable=PropertyMock, return_value=bridees):
        view.clear_items()
        await view._build_home()
    texte = "\n".join(i.content for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay))
    check("bridée" in texte and "Serveur protégé" not in texte,
          "permissions manquantes : l'accueil signale les protections bridées au lieu de « protégé »",
          texte[-200:])

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
