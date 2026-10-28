#!/usr/bin/env python3
"""Configuration guidée de /setup (brief V6, point 20), sur le bot booté.

Sécurité → Logs → Tickets → Bienvenue → Rôles. On vérifie : avancer, quitter
puis reprendre à la même étape, terminer, et qu'ouvrir les étapes n'active
AUCUN module (« ne jamais activer un système parce que son écran a été ouvert »).

    python3 tools/setup_guide_e2e.py
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


def bouton(view, debut: str):
    return next((it for top in view.children for it in walk(top)
                 if isinstance(it, discord.ui.Button) and str(it.label or "").startswith(debut)), None)


def textes(view) -> str:
    return "\n".join(it.content for top in view.children for it in walk(top) if isinstance(it, discord.ui.TextDisplay))


async def cliquer(view, debut: str) -> None:
    b = bouton(view, debut)
    if b is None:
        raise AssertionError(f"bouton « {debut} » absent sur la page {view.page!r}")
    await b.callback(interaction(view.bot))
    await h.settle(idle=0.2, maximum=2)


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    from cogs import setup_experience_v74 as v74
    from cogs import setup_v2_core as core

    avant = {m: await core.module_state(bot, h.GID, m) for m in ("security", "logs", "tickets", "welcome", "roles")}
    view = await build(bot, guild, None)
    check(bouton(view, "Configuration guidée") is not None, "l'accueil propose la configuration guidée")

    await cliquer(view, "Configuration guidée")
    check(view.page == "security" and "étape 1/5 : Sécurité" in textes(view), "étape 1 : Sécurité", textes(view)[-200:])
    await cliquer(view, "Étape suivante")
    check(view.page == "logs" and "étape 2/5 : Logs" in textes(view), "étape 2 : Logs")
    check(await v74.guide_step_saved(bot, h.GID) == 1, "l'étape est enregistrée")

    await cliquer(view, "Quitter le guide")
    check(view.page is None, "quitter ramène à l'accueil")
    view = await build(bot, guild, None)  # nouvelle ouverture de /setup
    check(bouton(view, "Reprendre la configuration guidée (2/5)") is not None, "l'accueil propose de reprendre à l'étape 2")
    await cliquer(view, "Reprendre")
    check(view.page == "logs", "reprendre rouvre l'étape 2 (Logs)")

    for _ in range(3):
        await cliquer(view, "Étape suivante")
    check(view.page == "roles" and bouton(view, "Terminer") is not None, "dernière étape : Rôles, bouton Terminer")
    await cliquer(view, "Terminer")
    check(view.page is None and await v74.guide_step_saved(bot, h.GID) is None, "terminer efface la progression")

    apres = {m: await core.module_state(bot, h.GID, m) for m in avant}
    check(apres == avant, "parcourir le guide n'a activé ni coupé aucun module", f"{avant} → {apres}")

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
