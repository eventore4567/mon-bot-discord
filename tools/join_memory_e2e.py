#!/usr/bin/env python3
"""Arrivée d'un membre sur le bot booté : la carte « Membre arrivé » rappelle ce que
le serveur sait déjà de la personne — départs passés, sanctions, compte récent.

    python3 tools/join_memory_e2e.py
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

MOD = dict(author_id=h.MOD_ID, author_roles=(h.MOD_ROLE_ID,))
OLD_ID = 100000000000000555  # identifiant de 2015 : un vieux compte


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    check(bot.get_cog("MemberDataRetentionV17") is not None,
          "le journal de conservation (source des départs) est chargé comme en production")

    def log_card(since: int) -> str:
        return h.visible_text([c for c in h.CALLS[since:] if c[1] == f"/channels/{h.LOGCID}/messages"])

    async def join(uid: int, name: str, *, is_bot: bool = False) -> str:
        data = h.member_payload(uid, name, [])
        data["user"]["bot"] = is_bot
        data["joined_at"] = discord.utils.utcnow().isoformat()  # chaque séjour a sa date d'arrivée
        data["guild_id"] = str(h.GID)
        since = len(h.CALLS)
        bot._connection.parse_guild_member_add(data)
        await h.settle(idle=0.8, maximum=6)
        return log_card(since)

    async def leave(uid: int, name: str) -> str:
        since = len(h.CALLS)
        bot._connection.parse_guild_member_remove({"guild_id": str(h.GID), "user": h.user(uid, name)})
        await h.settle(idle=0.8, maximum=6)
        return log_card(since)

    newcomer = h.next_id()
    shown = await join(newcomer, "nouveau")
    check("Membre arrivé" in shown and "**Mémoire :**" in shown and "première venue connue" in shown,
          "première arrivée : « première venue connue »", shown[-220:])
    check("compte créé il y a" in shown, "un compte créé à l'instant est signalé", shown[-220:])

    since = len(h.CALLS)
    await asyncio.wait_for(h.run_prefix(bot, guild, f"+warn <@{newcomer}> spam répété", **MOD), 15)
    await h.settle(idle=0.4, maximum=3)
    check("avertissement" in h.visible_text(h.CALLS[since:]).lower(), "le modérateur avertit le nouveau venu (vraie commande)")
    await bot.db.execute(
        "INSERT INTO sanctions (guild_id, case_number, user_id, moderator_id, action, reason, created_at) "
        "VALUES (?, 9001, ?, ?, 'unmute', 'levée', strftime('%s','now'))", (h.GID, newcomer, h.MOD_ID),
    )
    await leave(newcomer, "nouveau")
    shown = await join(newcomer, "nouveau")
    check("revient : parti 1 fois" in shown, "au retour : le départ précédent est rappelé", shown[-220:])
    check("1 sanction passée ici (1 avertissement)" in shown,
          "au retour : l'avertissement d'avant le départ est rappelé, la levée n'est pas comptée", shown[-220:])

    shown = await leave(newcomer, "nouveau")
    check("Membre parti" in shown, "le second départ en quelques secondes a sa propre carte", shown[-220:])
    shown = await join(newcomer, "nouveau")
    check("revient : parti 2 fois" in shown, "deux départs : « parti 2 fois »", shown[-220:])

    # Le même événement d'arrivée reçu deux fois (même date d'arrivée) : une seule carte.
    data = h.member_payload(newcomer, "nouveau", [])
    data["guild_id"] = str(h.GID)
    data["joined_at"] = guild.get_member(newcomer).joined_at.isoformat()
    since = len(h.CALLS)
    bot._connection.parse_guild_member_add(data)
    await h.settle(idle=0.8, maximum=6)
    check("Membre arrivé" not in log_card(since), "un événement reçu en double ne fait toujours qu'une carte",
          log_card(since)[-220:])

    shown = await join(OLD_ID, "ancien")
    check("première venue connue" in shown and "compte créé il y a" not in shown,
          "un vieux compte n'est pas signalé comme récent", shown[-220:])

    shown = await join(h.next_id(), "robot", is_bot=True)
    check("Membre arrivé" in shown and "Mémoire" not in shown, "un bot qui arrive n'a pas de ligne de mémoire", shown[-220:])

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
