#!/usr/bin/env python3
"""L'anti-raid automatique détecte vraiment un raid (27/11/2026).

Jayden : « que SentriX détecte vraiment un raid ». Une vague de comptes neufs
arrive en quelques secondes : le mode raid s'arme seul et les expulse ; une
arrivée isolée normale n'est pas touchée.

    python3 tools/anti_raid_detection_e2e.py
"""
from __future__ import annotations

import asyncio
import datetime as dt
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
from suggestions_e2e import RESULTS, check  # noqa: E402


def nouveau_compte(bot, guild, numero: int) -> discord.Member:
    """Compte créé il y a une heure, avatar par défaut, qui vient d'arriver."""
    cree = discord.utils.utcnow() - dt.timedelta(hours=1)
    uid = discord.utils.time_snowflake(cree) + numero
    data = h.member_payload(uid, f"raid{numero}", [])
    data["joined_at"] = discord.utils.utcnow().isoformat()
    data["user"]["avatar"] = None
    membre = discord.Member(data=data, guild=guild, state=bot._connection)
    guild._add_member(membre)
    return membre


async def main() -> int:
    from cogs import raid_mode

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    await bot.db.execute("INSERT INTO automod_settings (guild_id) VALUES (?) ON CONFLICT(guild_id) DO NOTHING", (h.GID,))
    await bot.db.execute("UPDATE automod_settings SET antiraid=1 WHERE guild_id=?", (h.GID,))
    bot.get_cog("Automod").automod_cache.clear()

    debut = len(h.CALLS)
    membres = [nouveau_compte(bot, guild, i) for i in range(12)]
    for membre in membres:
        bot.dispatch("member_join", membre)
        await asyncio.sleep(0.15)
    await h.settle(idle=1.5, maximum=15)
    expulses = {int(m.group(1)) for meth, p, _ in h.CALLS[debut:]
                if meth == "DELETE" and (m := re.fullmatch(rf"/guilds/{h.GID}/members/(\d+)", p))}
    check(raid_mode.actif(guild.id), "12 comptes neufs en 2 s : le mode raid s'arme tout seul")
    check(len(expulses & {m.id for m in membres}) >= 10,
          "les comptes du raid sont expulsés", f"{len(expulses & {m.id for m in membres})}/12 expulsés")

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
