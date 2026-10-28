#!/usr/bin/env python3
"""/setup → Logs : états réels et bouton « Envoyer un test » (brief V6, point 36).

28/10/2026 : la page affichait « ACTIF — aucun salon » pour des catégories qui
n'envoyaient rien, et il n'existait aucun moyen de vérifier une destination.

    python3 tools/logs_setup_test_e2e.py
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
from setup_sweep import build, interaction, walk  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), label))
    print(("OK   " if ok else "ÉCHEC ") + label + (f" — {detail}" if detail and not ok else ""))


def bouton(view, libelle):
    return next(it for top in view.children for it in walk(top)
                if isinstance(it, discord.ui.Button) and it.label == libelle)


def textes(view) -> str:
    return "\n".join(it.content for top in view.children for it in walk(top) if isinstance(it, discord.ui.TextDisplay))


async def cliquer_test(bot, guild, categorie: str):
    view = await build(bot, guild, "logs")
    view.backend.selected_log = categorie
    view.clear_items()
    await view._build_page("logs")
    since = len(h.CALLS)
    await bouton(view, "Envoyer un test").callback(interaction(bot))
    await h.settle(idle=0.5, maximum=5)
    calls = h.CALLS[since:]
    reponse = h.visible_text([c for c in calls if "/webhooks/" in c[1]]).replace("## Information", "").strip()
    carte = h.visible_text([c for c in calls if c[1].startswith(f"/channels/{h.LOGCID}/messages")])
    return reponse, carte


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    from utils import log_service
    await log_service.set_log_config(bot, h.GID, "moderation", channel_id=h.LOGCID, enabled=True)

    view = await build(bot, guild, "logs")
    t = textes(view)
    check("ACTIF — *aucun salon*" not in t, "plus aucune catégorie « ACTIF » sans salon", t[:200])
    check("🟢 Actif — <#" in t, "une catégorie avec salon valide est « Actif »")

    reponse, carte = await cliquer_test(bot, guild, "moderation")
    check("Test des logs" in carte, "le test arrive dans le salon des logs", carte[:160])
    check("Test envoyé dans <#" in reponse, "réponse privée : test envoyé", reponse[:160])

    await log_service.set_log_config(bot, h.GID, "soundboard", channel_id=None, enabled=False)
    reponse, carte = await cliquer_test(bot, guild, "soundboard")
    check(not carte and "Test impossible" in reponse, "catégorie sans salon : test refusé avec la raison", reponse[:160])

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
