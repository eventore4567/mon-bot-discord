#!/usr/bin/env python3
"""Logs : une suppression multiple devient UNE carte (26/11/2026).

Avant : un ban avec effacement de l'historique, ou la purge d'un autre bot,
produisait une carte « Message supprimé » par message dans le salon de logs.

    python3 tools/logs_rafale_e2e.py
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


async def main() -> int:
    from utils import log_service

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    await log_service.set_log_channel(bot, guild.id, "messages", h.LOGCID)
    await log_service.set_log_enabled(bot, guild.id, "messages", True)
    from cogs import setup_v2_core as core
    await core.set_module_enabled(bot, guild.id, "logs", True, actor_id=h.ADMIN_ID)

    async def poster(n):
        ids = []
        for i in range(n):
            message = h.build_message(bot, guild, f"message de test numéro {i} un peu long pour l'aperçu",
                                      author_id=h.TARGET_ID if i % 2 else h.SECOND_ID, author_name="membre")
            ids.append(message.id)
            bot.dispatch("message", message)
        await h.settle(idle=0.5, maximum=4)
        return ids

    def cartes_de_logs(appels):
        return [js for m, p, js in appels if m == "POST" and p == f"/channels/{h.LOGCID}/messages"]

    async def supprimer(ids):
        debut = len(h.CALLS)
        bot.dispatch("raw_bulk_message_delete", discord.RawBulkMessageDeleteEvent(
            {"ids": [str(i) for i in ids], "channel_id": str(h.CID), "guild_id": str(h.GID)}))
        await h.settle(idle=2.0, maximum=10)
        return cartes_de_logs(h.CALLS[debut:])

    cartes = await supprimer(await poster(12))
    check(len(cartes) == 1, "12 messages supprimés d'un coup donnent UNE carte", f"{len(cartes)} carte(s)")
    texte = str(cartes[0]) if cartes else ""
    check("Suppression multiple" in texte and "12" in texte, "la carte dit combien et quel salon", texte[:200])
    check(f"<@{h.TARGET_ID}>" in texte and f"<@{h.SECOND_ID}>" in texte, "la carte liste les auteurs")

    cartes = await supprimer(await poster(2))
    check(len(cartes) == 2, "2 messages gardent leur carte chacun (pas de regroupement inutile)",
          f"{len(cartes)} carte(s)")

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
