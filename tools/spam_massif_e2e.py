#!/usr/bin/env python3
"""Gros spam : mute immédiat, sans rappel ni avertissement (27/11/2026).

    python3 tools/spam_massif_e2e.py
"""
from __future__ import annotations

import asyncio
import datetime as dt
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


def message_a(bot, guild, texte, auteur, instant):
    mid = discord.utils.time_snowflake(instant) + (h.next_id() % 4000)
    data = h.message_payload(mid, h.CID, texte, auteur, "membre")
    # Membre établi (arrivé il y a 200 jours) : c'est lui qui a droit au rappel.
    data["member"] = h.member_payload(auteur, "membre", [h.MEMBER_ROLE_ID])
    data["member"]["joined_at"] = (discord.utils.utcnow() - dt.timedelta(days=200)).isoformat()
    return discord.Message(state=bot._connection, channel=guild.get_channel(h.CID), data=data)


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    await bot.db.execute("INSERT INTO automod_settings (guild_id) VALUES (?) ON CONFLICT(guild_id) DO NOTHING", (h.GID,))
    await bot.db.execute("UPDATE automod_settings SET antispam=1 WHERE guild_id=?", (h.GID,))
    automod = bot.get_cog("Automod")
    automod.automod_cache.clear()

    async def serie(auteur, n, ecart):
        debut = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=n * ecart + 1)
        avant = len(h.CALLS)
        for i in range(n):
            await automod.on_message(message_a(bot, guild, f"flood {i} lol", auteur, debut + dt.timedelta(seconds=i * ecart)))
        await h.settle(idle=1.5, maximum=6)
        appels = h.CALLS[avant:]
        mute = any(m == "PATCH" and p.endswith(f"/members/{auteur}") and (js or {}).get("communication_disabled_until")
                   for m, p, js in appels)
        texte = h.visible_text(appels)
        return mute, texte

    mute, texte = await serie(100000000000000501, 5, 0.2)
    check(mute, "5 messages en 1 s : mute immédiat (pas de rappel d'abord)", texte[-200:])
    check("spam massif" in texte, "le message public dit « spam massif »", texte[-200:])

    mute, texte = await serie(100000000000000502, 5, 1.1)
    check(not mute, "5 messages en 5 s (rafale ordinaire) : rappel d'abord, pas de mute", texte[-200:])

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
