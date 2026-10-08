#!/usr/bin/env python3
"""Page « Suggestions » du /setup servi (V74), sur le bot booté comme en production.

    python3 tools/setup_suggestions_e2e.py
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
from suggestions_e2e import RESULTS, _buttons, check  # noqa: E402
from welcome_e2e import admin_interaction, control, posts, setup_page  # noqa: E402


def count(item) -> int:
    children = list(getattr(item, "children", []) or [])
    if getattr(item, "accessory", None) is not None:
        children.append(item.accessory)
    return 1 + sum(count(child) for child in children)


def texts(view) -> str:
    out = []

    def walk(item):
        for attr in ("content", "label", "placeholder"):
            value = getattr(item, attr, None)
            if isinstance(value, str):
                out.append(value)
        for child in list(getattr(item, "children", []) or []):
            walk(child)

    for child in view.children:
        walk(child)
    return "\n".join(out)


async def main() -> int:
    from cogs import language_runtime
    from cogs import setup_experience_v74 as v74
    from services import suggestions as svc

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)

    # 1 — L'accueil du /setup ouvre la page Suggestions.
    home = v74.SentriXSetupV74(bot, guild, h.ADMIN_ID)
    await home.prepare()
    menu = control(home, lambda i: isinstance(i, discord.ui.Select)
                   and any(o.value == "suggestions" for o in getattr(i, "options", [])))
    check(menu is not None, "l'accueil du /setup propose « Suggestions »")

    # 2 — Page vierge : non configurée, publication refusée avec une raison.
    view = await setup_page(bot, guild, "suggestions")
    shown = texts(view)
    check("Suggestions" in shown and "Non configuré" in shown, "la page affiche l'état réel (non configuré)", shown[:200])
    total = sum(count(child) for child in view.children)
    check(total <= 40, "la page respecte la limite Discord de 40 composants", str(total))
    publish = control(view, lambda i: getattr(i, "label", None) == "Publier la boîte à suggestions")
    since = len(h.CALLS)
    await publish.callback(admin_interaction(bot))
    await h.settle(idle=0.3, maximum=2)
    check("Choisissez d'abord le salon" in h.visible_text(h.CALLS[since:]), "publier sans salon : refus expliqué")

    # 3 — Salon, délai, anonymat, fils : chaque contrôle écrit le vrai réglage.
    select = control(view, lambda i: isinstance(i, discord.ui.ChannelSelect))
    select._values = [guild.get_channel(h.CID)]
    await select.callback(admin_interaction(bot))
    await h.settle(idle=0.3, maximum=2)
    settings = await svc.get_settings(bot.db, h.GID)
    check(settings.channel_id == h.CID, "le salon choisi est enregistré")

    view = await setup_page(bot, guild, "suggestions")
    cooldown = control(view, lambda i: isinstance(i, discord.ui.Select) and not isinstance(i, discord.ui.ChannelSelect)
                       and any(o.value == "3600" for o in getattr(i, "options", [])))
    cooldown._values = ["3600"]
    await cooldown.callback(admin_interaction(bot))
    await h.settle(idle=0.3, maximum=2)
    check((await svc.get_settings(bot.db, h.GID)).cooldown_seconds == 3600, "le délai choisi est enregistré")

    view = await setup_page(bot, guild, "suggestions")
    anonymous = control(view, lambda i: str(getattr(i, "label", "")).startswith("Auteur masqué"))
    await anonymous.callback(admin_interaction(bot))
    await h.settle(idle=0.3, maximum=2)
    view = await setup_page(bot, guild, "suggestions")
    threads = control(view, lambda i: str(getattr(i, "label", "")).startswith("Fil de discussion"))
    await threads.callback(admin_interaction(bot))
    await h.settle(idle=0.3, maximum=2)
    settings = await svc.get_settings(bot.db, h.GID)
    check(settings.anonymous and settings.threads and settings.cooldown_seconds == 3600 and settings.channel_id == h.CID,
          "anonymat et fils activés sans écraser le salon ni le délai", str(settings))
    view = await setup_page(bot, guild, "suggestions")
    shown = texts(view)
    check(f"<#{h.CID}>" in shown and "1 h" in shown and "Auteur masqué : Oui" in shown,
          "la page relit les réglages enregistrés", shown[:300])

    # 4 — Publier la boîte dans le salon configuré, avec son bouton.
    since = len(h.CALLS)
    publish = control(view, lambda i: getattr(i, "label", None) == "Publier la boîte à suggestions")
    await publish.callback(admin_interaction(bot))
    await h.settle(idle=0.4, maximum=3)
    sent = posts(since, h.CID)
    labels = [b.get("label") for b in _buttons({"components": sent[0].get("components", [])})] if sent else []
    check(len(sent) == 1 and "Créer une suggestion" in labels, "la boîte est publiée avec son bouton", str(labels))
    check("Boîte à suggestions publiée" in h.visible_text(h.CALLS[since:]), "l'administrateur reçoit le lien")

    # 5 — Chaque réglage laisse une trace dans #logs.
    since = len(h.CALLS)
    view = await setup_page(bot, guild, "suggestions")
    threads = control(view, lambda i: str(getattr(i, "label", "")).startswith("Fil de discussion"))
    await threads.callback(admin_interaction(bot))
    await h.settle(idle=0.4, maximum=3)
    check(len(posts(since, h.LOGCID)) == 1, "un réglage = une carte dans #logs", str(len(posts(since, h.LOGCID))))

    # 6 — Serveur en anglais : la page parle anglais.
    await language_runtime.set_language(bot, h.GID, language_runtime.LANG_EN)
    view = await setup_page(bot, guild, "suggestions")
    shown = texts(view)
    check("Post the suggestion box" in shown and "Hide the author: Yes" in shown, "la page suit la langue du serveur", shown[:300])

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
