#!/usr/bin/env python3
"""Aucun envoi au nom d'un membre ne peut faire sonner @everyone sans son droit.

Mesuré le 08/10/2026 sur le bot booté : un modérateur (Gérer les messages, sans
« Mentionner @everyone ») programmait « @everyone <@&rôle> » et le bot pinguait
tout le serveur et un rôle non mentionnable ; un sticky contenant @everyone
aurait repingué le serveur à chaque republication. Le bot n'avait aucun
allowed_mentions par défaut.

    python3 tools/mentions_e2e.py
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

MOD = dict(author_id=h.MOD_ID, author_name="modo", author_roles=(h.MOD_ROLE_ID,))
ADMIN = dict(author_id=h.ADMIN_ID, author_roles=(h.ADMIN_ROLE_ID,))
MEMBER = dict(author_id=h.TARGET_ID, author_name="cible", author_roles=(h.MEMBER_ROLE_ID,))


def sent_to(since: int, channel_id: int) -> list[dict]:
    return [js or {} for m, p, js in h.CALLS[since:] if m == "POST" and p == f"/channels/{channel_id}/messages"]


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    plus = bot.get_cog("SentriXPlus")

    async def schedule_and_fire(text: str, who: dict) -> dict:
        await bot.db.execute("DELETE FROM sentrix_scheduled_messages")
        await asyncio.wait_for(h.run_prefix(bot, guild, f"+schedule-send 10m <#{h.CID}> {text}", **who), 15)
        await h.settle(idle=0.3, maximum=2)
        await bot.db.execute("UPDATE sentrix_scheduled_messages SET due_at=0")
        since = len(h.CALLS)
        await plus.scheduled_worker.coro(plus)
        await h.settle(idle=0.3, maximum=2)
        posts = [p for p in sent_to(since, h.CID) if "réunion" in str(p.get("content"))]
        return (posts[0].get("allowed_mentions") or {}) if posts else {}

    # 1 — Modérateur sans « Mentionner @everyone » : ni @everyone ni rôle non mentionnable.
    mentions = await schedule_and_fire(f"@everyone <@&{h.MEMBER_ROLE_ID}> <@&{h.PING_ROLE_ID}> réunion", MOD)
    check("everyone" not in mentions.get("parse", []) and "roles" not in mentions.get("parse", []),
          "modérateur : le message programmé ne fait pas sonner @everyone", str(mentions))
    roles = [int(r) for r in mentions.get("roles", [])]
    check(h.PING_ROLE_ID in roles and h.MEMBER_ROLE_ID not in roles,
          "modérateur : seul le rôle mentionnable peut sonner, comme sur Discord", str(roles))

    # 2 — Administrateur : son @everyone programmé sonne.
    mentions = await schedule_and_fire("@everyone réunion", ADMIN)
    check("everyone" in mentions.get("parse", []), "administrateur : son @everyone programmé sonne", str(mentions))

    # 3 — Sticky : jamais de notification à la republication.
    await asyncio.wait_for(h.run_prefix(bot, guild, f"+sticky-set <#{h.CID}> @everyone lisez le règlement", **ADMIN), 15)
    await h.settle(idle=0.3, maximum=2)
    plus._no_sticky.clear()
    since = len(h.CALLS)
    for index in range(6):
        bot.dispatch("message", h.build_message(bot, guild, f"message {index}", **MEMBER))
        await h.settle(idle=0.2, maximum=1)
    reposts = [p for p in sent_to(since, h.CID) if "lisez le règlement" in str(p.get("content"))]
    check(len(reposts) >= 1, "le sticky est bien republié", str(len(reposts)))
    check(all((p.get("allowed_mentions") or {}).get("parse") == [] for p in reposts),
          "le sticky republié ne notifie personne", str([p.get("allowed_mentions") for p in reposts]))

    # 4 — Défaut du bot : un envoi brut ne sonne plus @everyone ; un envoi explicite si.
    channel = guild.get_channel(h.CID)
    since = len(h.CALLS)
    await channel.send("@everyone envoi brut")
    await channel.send("@everyone envoi voulu", allowed_mentions=discord.AllowedMentions(everyone=True))
    raw, wanted = sent_to(since, h.CID)[:2]
    # Sans allowed_mentions du tout, Discord fait sonner TOUT : l'absence n'est pas une protection.
    check(raw.get("allowed_mentions") is not None
          and "everyone" not in raw["allowed_mentions"].get("parse", []),
          "défaut du bot : un envoi brut ne fait pas sonner @everyone", str(raw.get("allowed_mentions")))
    check("users" in (raw.get("allowed_mentions") or {}).get("parse", []) and
          "roles" in (raw.get("allowed_mentions") or {}).get("parse", []),
          "défaut du bot : membres et rôles restent notifiés comme avant", str(raw.get("allowed_mentions")))
    check("everyone" in (wanted.get("allowed_mentions") or {}).get("parse", []),
          "un @everyone explicitement autorisé sonne toujours", str(wanted.get("allowed_mentions")))

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
