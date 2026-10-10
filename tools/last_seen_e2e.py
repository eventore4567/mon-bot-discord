#!/usr/bin/env python3
"""Mémoire côté membre sur le bot booté : sa propre fiche (+level, +balance) dit ce
qui a changé depuis la dernière fois qu'il l'a vue.

    python3 tools/last_seen_e2e.py
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
MARK = "depuis votre dernier coup d'œil"


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    db = bot.db

    async def run(command: str, who: dict) -> str:
        since = len(h.CALLS)
        await asyncio.wait_for(h.run_prefix(bot, guild, command, **who), 15)
        await h.settle(idle=0.3, maximum=2)
        return h.visible_text([c for c in h.CALLS[since:] if c[1] == f"/channels/{h.CID}/messages"])

    async def age(key: str, days: int) -> None:
        await db.execute("UPDATE sentrix_last_seen SET seen_at = seen_at - ? WHERE user_id = ? AND key = ?",
                         (days * 86400, h.SECOND_ID, key))

    shown = await run("+level", MEMBER)
    check("Niveau" in shown and MARK not in shown and "Rien de neuf" not in shown,
          "première consultation : la fiche n'invente aucun écart", shown[:200])
    async def level() -> int:
        row = await db.fetchone("SELECT level FROM levels WHERE guild_id = ? AND user_id = ?", (h.GID, h.SECOND_ID))
        return int(row["level"]) if row else 0

    old_level = await level()
    await run(f"+add-xp <@{h.SECOND_ID}> 300", ADMIN)
    gained = await level() - old_level
    shown = await run("+level", MEMBER)
    check("+300 XP" in shown and f"{MARK}, il y a 1 min" in shown, "après 300 XP : « +300 XP … depuis votre dernier coup d'œil »",
          shown[:300])
    expected = f"+{gained} niveau{'x' if gained > 1 else ''}"
    check((expected in shown) == (gained > 0), f"le gain de niveau réel ({gained}) est dit exactement", shown[:300])
    shown = await run("+level", MEMBER)
    check(MARK not in shown and "Rien de neuf" not in shown, "consultation suivante sans changement récent : rien", shown[:200])
    await age("level", 2)
    shown = await run("+level", MEMBER)
    check("Rien de neuf depuis votre dernier coup d'œil, il y a 2 j" in shown,
          "deux jours sans changement : « Rien de neuf … il y a 2 j »", shown[:300])

    before = await db.fetchone("SELECT COUNT(*) AS n FROM sentrix_last_seen WHERE user_id = ?", (h.TARGET_ID,))
    shown = await run(f"+level <@{h.TARGET_ID}>", MEMBER)
    after = await db.fetchone("SELECT COUNT(*) AS n FROM sentrix_last_seen WHERE user_id = ?", (h.TARGET_ID,))
    check(MARK not in shown and before["n"] == after["n"] == 0,
          "la fiche d'un autre membre : aucune mémoire lue ni écrite", f"{shown[:120]} | {before['n']}->{after['n']}")

    shown = await run("+balance", MEMBER)
    check(MARK not in shown, "+balance, première fois : rien", shown[:200])
    await run(f"+give-money <@{h.SECOND_ID}> 500", ADMIN)
    shown = await run("+balance", MEMBER)
    check(f"+500 🪙 {MARK}" in shown, "+balance après un don : « +500 🪙 depuis votre dernier coup d'œil »", shown[:300])
    await run(f"+pay <@{h.TARGET_ID}> 100", MEMBER)
    shown = await run("+balance", MEMBER)
    check(f"−100 🪙 {MARK}" in shown, "+balance après un paiement : « −100 🪙 … »", shown[:300])

    # +stats : sa propre fiche complète, avec sa propre mémoire.
    shown = await run("+stats", MEMBER)
    check("Rien de neuf" not in shown and MARK not in shown, "+stats, première fois : rien", shown[-200:])
    await run(f"+add-xp <@{h.SECOND_ID}> 50", ADMIN)
    await run(f"+give-money <@{h.SECOND_ID}> 25", ADMIN)
    shown = await run("+stats", MEMBER)
    check(f"+50 XP" in shown and "+25 🪙" in shown and MARK in shown,
          "+stats après de l'XP et de l'argent : « +50 XP, +25 🪙 … depuis votre dernier coup d'œil »", shown[-300:])

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
