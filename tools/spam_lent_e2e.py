#!/usr/bin/env python3
"""Spam lent : un message toutes les 1,7 s est arrêté au 6e, pas au 10e (26/11/2026).

    python3 tools/spam_lent_e2e.py
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


def message_a(bot, guild, texte, auteur, instant):
    """Message dont l'heure d'envoi Discord (snowflake) est « instant »."""
    mid = discord.utils.time_snowflake(instant) + (h.next_id() % 4000)
    data = h.message_payload(mid, h.CID, texte, auteur, "membre")
    data["member"] = h.member_payload(auteur, "membre", [h.MEMBER_ROLE_ID])
    return discord.Message(state=bot._connection, channel=guild.get_channel(h.CID), data=data)


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    await bot.db.execute("INSERT INTO automod_settings (guild_id) VALUES (?) ON CONFLICT(guild_id) DO NOTHING", (h.GID,))
    await bot.db.execute("UPDATE automod_settings SET antispam=1 WHERE guild_id=?", (h.GID,))
    automod = bot.get_cog("Automod")
    automod.automod_cache.clear()

    async def serie(auteur, n, ecart, texte="pub serveur numero {i} rejoins vite"):
        debut = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=n * ecart)
        reaction = None
        for i in range(n):
            avant = len(h.CALLS)
            message = message_a(bot, guild, texte.format(i=i), auteur,
                                debut + dt.timedelta(seconds=i * ecart))
            await automod.on_message(message)
            await h.settle(idle=0.2, maximum=2)
            vu = h.visible_text(h.CALLS[avant:])
            if reaction is None and ("spam" in vu.casefold() or any(
                    m == "DELETE" or p.endswith("bulk-delete") for m, p, _ in h.CALLS[avant:])):
                reaction = i + 1
        return reaction

    reaction = await serie(h.TARGET_ID, 12, 1.7)
    check(reaction is not None and reaction <= 6, "un spam à 1 message / 1,7 s est arrêté au 6e message au plus",
          f"réaction au message {reaction}")
    calme = await serie(h.SECOND_ID, 6, 3.5)
    check(calme is None, "une conversation à 1 message / 3,5 s n'est jamais prise pour du spam", str(calme))

    commandes = await serie(h.MOD_ID, 8, 1.8, texte="+balance {i}")
    check(commandes is None, "8 commandes à 1,8 s d'écart ne sont pas prises pour du spam lent", str(commandes))

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
