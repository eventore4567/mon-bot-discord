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
    noms = ("Spam", "@everyone", "Pub", "Arnaques", "Insultes", "Raid", "Bots", "Nuke")
    check(all(n in texte for n in noms) and texte.count("Protection désactivée") == 1,
          "les 8 attaques sont nommées, et la cause commune n'est écrite qu'une fois")
    check("aucun message envoyé" in texte, "l'écran dit que c'est une simulation")
    check(" — " not in texte, "vue courte : pas le scénario de chaque attaque")
    composants = sum(1 for t in view.children for _ in walk(t))
    check(composants <= 40, f"l'écran reste sous la limite Discord ({composants}/40 composants)")
    check(len(texte) <= 3900, f"le texte tient dans un message ({len(texte)} caractères)")

    await bouton(view, "Activer la sécurité").callback(interaction(bot))
    await h.settle(idle=0.3, maximum=3)
    apres, texte = note(view), texts(view)
    print(texte)
    check(apres > avant and apres >= 75, f"après « Activer la sécurité », la note monte ({avant} → {apres})")
    check("Protection désactivée" not in texte, "plus aucune attaque annoncée comme non protégée")
    court = len(texte)
    check("**Bloqué** ·" in texte and court <= 900,
          f"serveur protégé : une seule ligne pour les attaques bloquées ({court} caractères)")

    await bouton(view, "Détail").callback(interaction(bot))
    await h.settle(idle=0.3, maximum=3)
    detail = texts(view)
    check(len(detail) > court and detail.count(" — ") == 9,
          f"« Détail » montre les 9 scénarios ({len(detail)} caractères)")
    await bouton(view, "Vue courte").callback(interaction(bot))
    await h.settle(idle=0.3, maximum=3)
    check(len(texts(view)) == court, "« Vue courte » revient à l'écran court")
    row = dict(await bot.db.get_automod(h.GID) or {})
    check(all(row.get(c) for c in ("antispam", "antiraid", "antinuke", "antiscam")),
          "les protections sont réellement enregistrées en base")

    await bouton(view, "Retour").callback(interaction(bot))
    await h.settle(idle=0.3, maximum=3)
    check("Sécurité" in texts(view) and "Votre serveur est protégé" in texts(view),
          "« Retour » revient à l'écran simple, qui dit « Votre serveur est protégé »")
    await bouton(view, "Personnaliser").callback(interaction(bot))
    await h.settle(idle=0.3, maximum=3)
    menus = [i.placeholder for t in view.children for i in walk(t) if isinstance(i, discord.ui.Select)]
    check("Configurer une protection" in menus, "« Personnaliser » ouvre l'écran complet d'avant")
    await bouton(view, "Vue simple").callback(interaction(bot))
    await h.settle(idle=0.3, maximum=3)
    check("Votre serveur est protégé" in texts(view), "« Vue simple » revient à l'écran simple")

    # 10/11/2026 : « les emojis ne sont pas animés ni personnalisés ». Avec le pack
    # synchronisé, les deux écrans doivent porter les icônes SentriX, pas ✅ / ❌.
    from utils import sentrix_emojis

    sentrix_emojis.amorcer({
        "sentrix_c_success": "<a:sentrix_c_success:1420000000000000111>",
        "sentrix_c_error": "<a:sentrix_c_error:1420000000000000222>",
        "sentrix_c_warning": "<a:sentrix_c_warning:1420000000000000333>",
        "sentrix_c_security": "<a:sentrix_c_security:1420000000000000444>",
        "sentrix_scan": "<:sentrix_scan:1420000000000000555>",
        "sentrix_c_search": "<a:sentrix_c_search:1420000000000000666>",
        "sentrix_c_return": "<a:sentrix_c_return:1420000000000000777>",
        "sentrix_c_settings": "<a:sentrix_c_settings:1420000000000000888>",
    })
    try:
        view = await SecurityCenterView(bot, guild, h.ADMIN_ID).build()
        simple = texts(view)
        icones = [i.emoji for t in view.children for i in walk(t)
                  if isinstance(i, discord.ui.Button) and i.emoji is not None]
        check("<a:sentrix_c_security:" in simple and "✅" not in simple and "▫️" not in simple,
              "écran simple : icônes SentriX animées, plus aucun emoji Unicode")
        check(icones and all(getattr(e, "id", None) for e in icones),
              f"les boutons portent des icônes SentriX ({len(icones)} boutons)")
        await bouton(view, "Tester ma sécurité").callback(interaction(bot))
        await h.settle(idle=0.3, maximum=3)
        crash = texts(view)
        check("<a:sentrix_c_success:" in crash and "✅" not in crash,
              "crash-test : « bloqué » porte l'icône SentriX animée")
        check("<:sentrix_scan:" in crash and "🧪" not in crash,
              "le titre du crash-test porte l'icône SentriX")
    finally:
        sentrix_emojis.reinitialiser()

    echecs = [label for ok, label in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(echecs)}/{len(RESULTS)} étapes réussies.")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    code = asyncio.run(main())
    sys.stdout.flush()
    os._exit(code)
