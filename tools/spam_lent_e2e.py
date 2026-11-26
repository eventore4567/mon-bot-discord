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


def reaction_pour(appels, auteur, ids) -> bool:
    """SentriX a réagi à CE membre : un de ses messages supprimé, ou un rappel qui le nomme."""
    for m, p, js in appels:
        if m == "DELETE" and any(p.endswith(f"/messages/{i}") for i in ids):
            return True
        if p.endswith("bulk-delete") and any(str(i) in map(str, (js or {}).get("messages", [])) for i in ids):
            return True
        if m == "POST" and f"<@{auteur}>" in str(js) and "spam" in str(js).casefold():
            return True
    return False


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
        ids = []
        for i in range(n):
            avant = len(h.CALLS)
            message = message_a(bot, guild, texte.format(i=i), auteur,
                                debut + dt.timedelta(seconds=i * ecart))
            ids.append(message.id)
            await automod.on_message(message)
            await h.settle(idle=1.5, maximum=4)
            if reaction is None and reaction_pour(h.CALLS[avant:], auteur, ids):
                reaction = i + 1
        return reaction

    reaction = await serie(h.TARGET_ID, 12, 1.7)
    check(reaction is not None and reaction <= 6, "un spam à 1 message / 1,7 s est arrêté au 6e message au plus",
          f"réaction au message {reaction}")
    calme = await serie(h.SECOND_ID, 6, 3.5)
    check(calme is None, "une conversation à 1 message / 3,5 s n'est jamais prise pour du spam", str(calme))

    # Revue Codex (PR #731) : une commande isolée au milieu n'annule pas la
    # détection d'un spam lent fait de messages ordinaires.
    debut = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=12)
    reaction_mixte = None
    textes = ["+balance"] + [f"rejoins mon serveur vite {i}" for i in range(7)]
    mixte, ids_mixte = h.AUTHOR_ID + 900, []
    for i, texte in enumerate(textes):
        avant = len(h.CALLS)
        message = message_a(bot, guild, texte, mixte, debut + dt.timedelta(seconds=i * 1.5))
        ids_mixte.append(message.id)
        await automod.on_message(message)
        await h.settle(idle=1.5, maximum=4)
        if reaction_mixte is None and reaction_pour(h.CALLS[avant:], mixte, ids_mixte):
            reaction_mixte = i + 1
    check(reaction_mixte is not None and reaction_mixte <= 7,
          "une commande puis 6 messages ordinaires (1 / 1,5 s) : arrêté au 6e message ordinaire", str(reaction_mixte))

    # Revue Codex (PR #731) : les commandes personnalisées ont leur propre préfixe.
    from utils import command_prefixes
    await command_prefixes.set_custom_prefix(bot, h.GID, "!")
    perso = await serie(h.SECOND_ID + 7, 8, 1.7, texte="!regles {i}")
    check(perso is None, "8 commandes personnalisées (préfixe !) ne sont pas prises pour du spam lent", str(perso))

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
