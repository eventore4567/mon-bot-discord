#!/usr/bin/env python3
"""Un serveur où personne n'a cliqué « Activer » : les membres peuvent jouer.

24/10/2026, Jayden : « personne peut lancer des commandes ». Depuis 885c1ec3, tout
module sans ligne module_settings était coupé : +balance, +daily, +level refusés à
chaque membre, et un panel de tickets publié ne répondait plus.

    python3 tools/member_commands_default_e2e.py
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

import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402

MEMBRE = dict(author_id=h.TARGET_ID, author_roles=(h.MEMBER_ROLE_ID,))


async def main() -> int:
    from cogs import setup_v2_core as core

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    await bot.db.execute("DELETE FROM module_settings WHERE guild_id=?", (h.GID,))
    core.invalidate_module_cache(h.GID)

    async def say(text: str) -> str:
        since = len(h.CALLS)
        await asyncio.wait_for(h.run_prefix(bot, guild, text, **MEMBRE), 20)
        await h.settle(idle=0.3, maximum=3)
        return re.sub(r"\s+", " ", h.visible_text(h.CALLS[since:]))

    for commande in ("+balance", "+daily", "+level"):
        t = await say(commande)
        check(t.strip() and "désactivé" not in t, f"{commande} répond à un membre sans réglage", t[:140])

    t = await say("+ticket")
    check("désactivé" in t, "+ticket sans aucun panel : module non configuré, dit clairement", t[:140])
    tickets = bot.get_cog("Tickets")
    panel_id = await tickets.create_panel(h.GID, "Support")
    await tickets.add_type(h.GID, panel_id, "Aide")
    await bot.db.execute("UPDATE ticket_panels_v2 SET channel_id=?, enabled=1 WHERE id=?", (h.CID, panel_id))
    core.invalidate_module_cache(h.GID)
    t = await say("+ticket")
    check("Support" in t and "désactivé" not in t, "un panel publié suffit : +ticket marche sans clic « Activer »", t[:140])

    await core.set_module_enabled(bot, h.GID, "economy", False)
    t = await say("+balance")
    check("désactivé" in t, "un admin qui coupe l'économie est toujours obéi", t[:140])
    check(await core.module_enabled(bot, h.GID, "security"), "la sécurité reste active sans réglage")

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
