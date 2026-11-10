#!/usr/bin/env python3
"""Crash-test de sécurité, sur le bot démarré.

1. serveur sans protection : le bouton « Tester ma sécurité » affiche une note basse
   et dit que chaque attaque passerait ;
2. « Activer la sécurité » depuis l'écran du test : la note monte, les attaques sont
   bloquées ;
3. la page reste sous la limite de composants et « Retour » revient à l'écran simple.

    python3 tools/crash_test_e2e.py
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
from setup_sweep import build, interaction, walk  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    RESULTS.append((bool(ok), label))
    print(("OK   " if ok else "FAIL ") + label)


def texts(view) -> str:
    return "\n".join(item.content for top in view.children for item in walk(top)
                     if isinstance(item, discord.ui.TextDisplay))


def bouton(view, libelle: str) -> discord.ui.Button:
    for top in view.children:
        for item in walk(top):
            if isinstance(item, discord.ui.Button) and item.label == libelle:
                return item
    raise AssertionError(f"bouton « {libelle} » introuvable")


def note(view) -> int:
    trouve = re.search(r"Crash-test · (\d+)/100", texts(view))
    return int(trouve.group(1)) if trouve else -1


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    from cogs import setup_v2_core as core

    await bot.db.execute("DELETE FROM module_settings WHERE guild_id=?", (h.GID,))
    await bot.db.execute("DELETE FROM automod_settings WHERE guild_id=?", (h.GID,))
    core.invalidate_module_cache(h.GID)
    bot.get_cog("Automod").automod_cache.clear()

    facade = await build(bot, guild, "security")
    libelles = [getattr(i, "label", None) for t in facade.children for i in walk(t)]
    check({"Activer la sécurité", "Tester ma sécurité", "Personnaliser"} <= set(libelles),
          f"/setup → Sécurité s'ouvre sur l'écran simple ({[l for l in libelles if l]})")
    check("Aucune protection active" in texts(facade), "serveur neuf : l'écran dit « Aucune protection active »")

    # La vue réellement affichée par la page (ses boutons la rafraîchissent elle-même).
    from cogs.complete_security_setup import SecurityCenterView

    view = await SecurityCenterView(bot, guild, h.ADMIN_ID).build()
    await bouton(view, "Tester ma sécurité").callback(interaction(bot))
    await h.settle(idle=0.3, maximum=3)
    avant, texte = note(view), texts(view)
    print(texte)
    check(0 <= avant <= 30, f"serveur sans protection : note basse ({avant}/100)")
    check(texte.count("Protection désactivée") == 8, "les 8 attaques sont annoncées comme non bloquées")
    check("aucun message envoyé" in texte, "l'écran dit que c'est une simulation")
    composants = sum(1 for t in view.children for _ in walk(t))
    check(composants <= 40, f"l'écran reste sous la limite Discord ({composants}/40 composants)")
    check(len(texte) <= 3900, f"le texte tient dans un message ({len(texte)} caractères)")

    await bouton(view, "Activer la sécurité").callback(interaction(bot))
    await h.settle(idle=0.3, maximum=3)
    apres, texte = note(view), texts(view)
    print(texte)
    check(apres > avant and apres >= 75, f"après « Activer la sécurité », la note monte ({avant} → {apres})")
    check("Protection désactivée" not in texte, "plus aucune attaque annoncée comme non protégée")
    row = dict(await bot.db.get_automod(h.GID) or {})
    check(all(row.get(c) for c in ("antispam", "antiraid", "antinuke", "antiscam")),
          "les protections sont réellement enregistrées en base")

    await bouton(view, "Retour").callback(interaction(bot))
    await h.settle(idle=0.3, maximum=3)
    check("# 🛡️ Sécurité" in texts(view) and "Votre serveur est protégé" in texts(view),
          "« Retour » revient à l'écran simple, qui dit « Votre serveur est protégé »")
    await bouton(view, "Personnaliser").callback(interaction(bot))
    await h.settle(idle=0.3, maximum=3)
    menus = [i.placeholder for t in view.children for i in walk(t) if isinstance(i, discord.ui.Select)]
    check("Configurer une protection" in menus, "« Personnaliser » ouvre l'écran complet d'avant")
    await bouton(view, "Vue simple").callback(interaction(bot))
    await h.settle(idle=0.3, maximum=3)
    check("# 🛡️ Sécurité" in texts(view), "« Vue simple » revient à l'écran simple")

    echecs = [label for ok, label in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(echecs)}/{len(RESULTS)} étapes réussies.")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    code = asyncio.run(main())
    sys.stdout.flush()
    os._exit(code)
