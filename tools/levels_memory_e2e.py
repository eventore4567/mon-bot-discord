#!/usr/bin/env python3
"""Niveaux sur le bot booté : quand le staff crée de l'XP, la confirmation rappelle
le niveau, le rang et les ajouts d'XP du staff — lus dans le fil des commandes.

    python3 tools/levels_memory_e2e.py
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

import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402

ADMIN = dict(author_id=h.ADMIN_ID, author_roles=(h.ADMIN_ROLE_ID,))
MEMBER = dict(author_id=h.SECOND_ID, author_roles=(h.MEMBER_ROLE_ID,))


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)

    async def run(command: str, who: dict) -> str:
        since = len(h.CALLS)
        await asyncio.wait_for(h.run_prefix(bot, guild, command, **who), 15)
        await h.settle(idle=0.3, maximum=2)
        return h.visible_text([c for c in h.CALLS[since:] if c[1] == f"/channels/{h.CID}/messages"])

    await bot.db.ensure_level(h.GID, h.SECOND_ID)
    # Un autre membre bien plus haut : le membre crédité reste 2e.
    await bot.db.execute("UPDATE levels SET level = 50, xp = 0 WHERE guild_id = ? AND user_id = ?", (h.GID, h.SECOND_ID))

    shown = await run(f"+add-xp <@{h.TARGET_ID}> 300", ADMIN)
    check("300 XP" in shown and "Réf. SX-" in shown, "+add-xp répond et porte sa référence", shown[-200:])
    row = await bot.db.fetchone("SELECT level FROM levels WHERE guild_id = ? AND user_id = ?", (h.GID, h.TARGET_ID))
    check(f"niveau {row['level']} · 2e du serveur" in shown,
          "le niveau et le rang réels après l'ajout sont rappelés (un autre membre est plus haut)", shown[-200:])
    check("1 ajout d'XP du staff en 30 j" in shown, "le premier ajout est compté", shown[-200:])

    shown = await run(f"+add-xp <@{h.TARGET_ID}> 200", ADMIN)
    check("2 ajouts d'XP du staff en 30 j" in shown, "le second ajout cumule (lu dans le fil des commandes)",
          shown[-200:])
    shown = await run(f"+set-xp <@{h.TARGET_ID}> 9000", ADMIN)
    check("3 ajouts d'XP du staff en 30 j" in shown, "+set-xp compte aussi", shown[-200:])
    await bot.db.execute("UPDATE levels SET level = 0, xp = 0 WHERE guild_id = ? AND user_id = ?", (h.GID, h.SECOND_ID))
    shown = await run(f"+add-xp <@{h.TARGET_ID}> 1", ADMIN)
    check("1er du serveur" in shown, "le rang suit la base : l'autre membre redescendu, il passe 1er", shown[-200:])

    shown = await run(f"+add-xp <@{h.ADMIN_ID}> 50", ADMIN)
    check("à soi-même" in shown, "un membre du staff qui se donne de l'XP est signalé", shown[-200:])

    shown = await run(f"+add-xp <@{h.TARGET_ID}> 10", MEMBER)
    check("ajout" not in shown, "un refus n'affiche aucune mémoire", shown[-200:])

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
