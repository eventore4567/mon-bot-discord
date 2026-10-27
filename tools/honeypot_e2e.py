#!/usr/bin/env python3
"""Salon piège (honeypot) : texte, image seule et commande sont tous attrapés.

27/10/2026, Jayden : « le honeypot marche pas quand on met des images et quand on
lance des commandes ». Le piège ne vise que les comptes « non vérifié » : un test fait
avec un compte membre, vérifié, staff ou placé au-dessus de SentriX ne déclenche
rien — par conception, mais en silence. La raison est maintenant tracée.

    python3 tools/honeypot_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402

NON_VERIFIE = 100000000000000301
IMAGE = {"id": "9001", "filename": "spam.png", "size": 10, "url": "https://cdn.discordapp.com/x/spam.png",
         "proxy_url": "https://media.discordapp.net/x/spam.png", "content_type": "image/png"}


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    state = bot._connection
    guild._add_role(discord.Role(guild=guild, state=state, data={
        "id": str(NON_VERIFIE), "name": "Non vérifié", "permissions": "0", "position": 1, "color": 0,
        "hoist": False, "managed": False, "mentionable": False}))
    v71 = sys.modules["cogs.security_verification_v71"]
    await v71.ensure_schema(bot)
    await bot.db.execute(
        "INSERT INTO honeypot_verification (guild_id, enabled, trap_channel_id, unverified_role_id, sanction, created_at) "
        "VALUES (?,1,?,?,'kick',?) ON CONFLICT(guild_id) DO UPDATE SET enabled=1, trap_channel_id=excluded.trap_channel_id, "
        "unverified_role_id=excluded.unverified_role_id", (h.GID, h.CID, NON_VERIFIE, int(time.time())))
    await v71.settings(bot, h.GID)
    await bot.db.execute("UPDATE sentrix_security_v71 SET honeypot_enabled=1, honeypot_action='kick', "
                         "honeypot_delete_message=1 WHERE guild_id=?", (h.GID,))

    async def poster(uid: int, roles: tuple, contenu: str, image: bool = False) -> list:
        guild._add_member(discord.Member(data=h.member_payload(uid, f"c{uid % 1000}", list(roles)), guild=guild, state=state))
        msg = h.build_message(bot, guild, contenu, author_id=uid, author_name=f"c{uid % 1000}", author_roles=roles)
        if image:
            msg.attachments = [discord.Attachment(data=IMAGE, state=state)]
        since = len(h.CALLS)
        bot.dispatch("message", msg)
        await h.settle(idle=0.5, maximum=4)
        return [(m, p) for m, p, _ in h.CALLS[since:] if m == "DELETE"]

    for nom, uid, contenu, image in (("texte", 100000000000000501, "nitro gratuit ici", False),
                                     ("image seule", 100000000000000502, "", True),
                                     ("commande", 100000000000000503, "+ping", False)):
        actes = await poster(uid, (NON_VERIFIE,), contenu, image)
        check(any("/messages/" in p for _m, p in actes) and any(p.endswith(f"/members/{uid}") for _m, p in actes),
              f"compte non vérifié, {nom} : message supprimé et compte sanctionné", str(actes))

    actes = await poster(100000000000000504, (h.MEMBER_ROLE_ID,), "salut")
    check(not any("/members/" in p for _m, p in actes), "un membre ordinaire n'est jamais sanctionné par le piège",
          str(actes))

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
