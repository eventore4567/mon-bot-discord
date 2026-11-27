#!/usr/bin/env python3
"""/setup → Sécurité : plus de mode raid manuel, l'anti-raid est automatique (27/11/2026).

    python3 tools/anti_raid_auto_e2e.py
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
from welcome_e2e import admin_interaction  # noqa: E402


async def main() -> int:
    from cogs import raid_mode
    from cogs import setup_experience_v74 as v74

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    view = v74.SentriXSetupV74(bot, guild, h.ADMIN_ID)
    await view.prepare()

    async def boutons():
        view.page = "section:securite"
        view.clear_items()
        await view._build_page(view.page)
        return [i for i in view.walk_children() if isinstance(i, discord.ui.Button)]

    libelles = [b.label for b in await boutons()]
    check(not any(str(l).startswith("Mode raid") for l in libelles), "plus de bouton manuel « Mode raid »", str(libelles))
    check(any(str(l).startswith("Raids") for l in libelles), "l'anti-raid automatique (« Raids ») reste", str(libelles))

    await raid_mode.armer_manuel(bot, guild, h.ADMIN_ID)
    desarmer = [b for b in await boutons() if b.label == "Désarmer le mode raid"]
    check(bool(desarmer), "un mode manuel déjà armé peut être désarmé")
    if desarmer:
        try:
            await desarmer[0].callback(admin_interaction(bot))
        except Exception:  # noqa: BLE001 — rafraîchissement non testé
            pass
    check(not raid_mode.est_manuel(guild.id), "le clic désarme le mode raid")
    libelles = [b.label for b in await boutons()]
    check("Désarmer le mode raid" not in libelles, "désarmé, le bouton disparaît", str(libelles))

    # Revue Codex (PR #734) : un second panneau resté ouvert ne réarme jamais.
    await raid_mode.armer_manuel(bot, guild, h.ADMIN_ID)
    vieux = [b for b in await boutons() if b.label == "Désarmer le mode raid"]
    for bouton in (vieux[0], vieux[0]) if vieux else ():
        try:
            await bouton.callback(admin_interaction(bot))
        except Exception:  # noqa: BLE001
            pass
    check(not raid_mode.est_manuel(guild.id), "deux clics sur « Désarmer » (deux panneaux) ne réarment jamais")

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
