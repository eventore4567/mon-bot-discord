#!/usr/bin/env python3
"""Navigation de /setup sur le bot booté : l'accueil à menu unique.

31/10/2026 : l'assistant guidé (Sécurité → Logs → Tickets → Bienvenue → Rôles)
doublonnait les pages ; il est remplacé par UN menu sur l'accueil. On vérifie :
chaque page principale s'ouvre depuis ce menu, « Retour » ramène à l'accueil, et
parcourir les pages n'active AUCUN module (« ne jamais activer un système parce
que son écran a été ouvert »).

    python3 tools/setup_guide_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
from unittest.mock import patch

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
    original = discord.Interaction.edit_original_response
    rendered = []
    async def capture(i, **kwargs):
        if kwargs.get("view") is not None:
            rendered.append(kwargs["view"])
        return await original(i, **kwargs)
    with patch.object(discord.Interaction, "edit_original_response", capture):
        await b.callback(interaction(view.bot))
    await h.settle(idle=0.2, maximum=2)
    return rendered[-1] if rendered else view


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    from cogs import setup_v2_core as core

    pages = ("security", "logs", "tickets", "welcome", "roles")
    avant = {m: await core.module_state(bot, h.GID, m) for m in pages}
    view = await build(bot, guild, None)
    menu = next((it for top in view.children for it in walk(top) if isinstance(it, discord.ui.Select)), None)
    valeurs = {o.value for o in getattr(menu, "options", [])}
    check(menu is not None and set(pages) <= valeurs, "l'accueil propose un menu avec les pages principales",
          str(sorted(valeurs)))

    for page in pages:
        menu = next(it for top in view.children for it in walk(top) if isinstance(it, discord.ui.Select))
        menu._values = [page]
        await menu.callback(interaction(bot))
        await h.settle(idle=0.2, maximum=2)
        check(view.page == page and bouton(view, "Retour") is not None, f"le menu ouvre la page {page}")
        view = await cliquer(view, "Retour")
        check(view.page is None, f"« Retour » ramène à l'accueil depuis {page}")

    apres = {m: await core.module_state(bot, h.GID, m) for m in avant}
    check(apres == avant, "parcourir les pages n'a activé ni coupé aucun module", f"{avant} → {apres}")

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
