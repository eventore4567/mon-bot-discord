#!/usr/bin/env python3
"""Une action staff = UNE carte dans #logs, avec le bon sujet et le vrai modérateur.

Chaque cas rejoue la commande puis l'événement que Discord renvoie ensuite
(mise à jour du membre, du salon). C'est l'angle mort de tools/log_trace_sweep.py,
qui ne voit que ce que la commande produit elle-même : +giverole y paraissait
« sans trace », une carte lui a été ajoutée, et cela faisait DEUX cartes en
production (mesuré le 08/10/2026).

    python3 tools/log_echo_e2e.py
"""
from __future__ import annotations

import asyncio
import copy
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


def logs_since(since: int) -> list[str]:
    return [
        h.visible_text([c])
        for c in h.CALLS[since:]
        if c[0] == "POST" and c[1] == f"/channels/{h.LOGCID}/messages"
    ]


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    admin = dict(author_id=h.ADMIN_ID, author_roles=(h.ADMIN_ROLE_ID,))
    target = guild.get_member(h.TARGET_ID)
    channel = guild.get_channel(h.CID)
    mod = f"<@{h.ADMIN_ID}>"
    member = f"<@{h.TARGET_ID}>"

    async def case(name: str, command: str, echo) -> list[str]:
        since = len(h.CALLS)
        await asyncio.wait_for(h.run_prefix(bot, guild, command, **admin), 15)
        await h.settle(idle=0.4, maximum=3)
        echo()
        await h.settle(idle=0.6, maximum=4)
        cards = logs_since(since)
        check(len(cards) == 1, f"{name} : une seule carte", f"{len(cards)} carte(s)")
        return cards

    def roles(plus=(), minus=()):
        def fire():
            before, after = copy.copy(target), copy.copy(target)
            before._roles = discord.utils.SnowflakeList(list(target._roles))
            after._roles = discord.utils.SnowflakeList([r for r in target._roles if r not in minus] + list(plus))
            bot.dispatch("member_update", before, after)
        return fire

    def nick(value):
        def fire():
            before, after = copy.copy(target), copy.copy(target)
            after.nick = value
            bot.dispatch("member_update", before, after)
        return fire

    def channel_change(**changes):
        def fire():
            before, after = copy.copy(channel), copy.copy(channel)
            for key, value in changes.items():
                setattr(after, key, value)
            bot.dispatch("guild_channel_update", before, after)
        return fire

    cards = await case("+giverole", f"+giverole {member} <@&{h.PING_ROLE_ID}>", roles(plus=[h.PING_ROLE_ID]))
    text = " ".join(cards)
    check(f"**Membre** · {member}" in text and f"par {mod}" in text,
          "+giverole : le membre en en-tête et le vrai modérateur, pas SentriX", text[:200])

    cards = await case("+removerole", f"+removerole {member} <@&{h.MEMBER_ROLE_ID}>", roles(minus=[h.MEMBER_ROLE_ID]))
    check(f"par {mod}" in " ".join(cards), "+removerole : le vrai modérateur")

    cards = await case("+nickname", f"+nickname {member} NouveauPseudo", nick("NouveauPseudo"))
    text = " ".join(cards)
    check(f"par {mod}" in text and "NouveauPseudo" in text, "+nickname : avant / après et le vrai modérateur", text[:200])

    for name, command, echo in (
        ("+slowmode", "+slowmode 30s", channel_change(slowmode_delay=30)),
        ("+lock", "+lock maintenance", channel_change()),
        ("+unlock", "+unlock", channel_change()),
    ):
        cards = await case(name, command, echo)
        text = " ".join(cards)
        check(f"**Salon** · <#{h.CID}>" in text and f"<#{h.ADMIN_ID}>" not in text,
              f"{name} : le salon visé en en-tête, jamais le modérateur", text[:200])

    since = len(h.CALLS)
    await asyncio.wait_for(h.run_prefix(bot, guild, f"+give-money {member} 500", **admin), 15)
    await h.settle(idle=0.4, maximum=3)
    text = " ".join(logs_since(since))
    check(f"**Membre** · {member}" in text, "+give-money : le membre crédité en en-tête", text[:200])

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
