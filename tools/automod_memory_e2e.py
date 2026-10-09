#!/usr/bin/env python3
"""AutoMod sur le bot booté : la carte d'incident rappelle les incidents passés du
membre (rang, types) et ce que le staff sait de lui.

    python3 tools/automod_memory_e2e.py
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

LINK = "regarde ça https://exemple-douteux.example/offre"
INVITE = "rejoins discord.gg/abcdefg"
MOD = dict(author_id=h.MOD_ID, author_roles=(h.MOD_ROLE_ID,))


async def main() -> int:
    bot = await h.boot(quiet=True)
    # load_extension crée un NOUVEL objet module : régler celui que le bot utilise.
    sys.modules["cogs.automod"].INCIDENT_LOG_DELAY_SECONDS = 0.1
    bot.get_cog("Moderation").SANCTION_DUPLICATE_TTL = 0
    guild = await h.setup_world(bot)
    automod = bot.get_cog("Automod")
    db = bot.db
    await db.execute("INSERT INTO automod_settings (guild_id) VALUES (?) ON CONFLICT(guild_id) DO NOTHING", (h.GID,))
    await db.execute("UPDATE automod_settings SET antilink=1, antiinvite=1 WHERE guild_id=?", (h.GID,))

    async def post(content: str, author_id: int) -> str:
        automod.automod_cache.clear()
        automod.incidents.clear()  # un nouvel incident, pas la suite du précédent
        message = h.build_message(bot, guild, content, author_id=author_id, author_name="cible",
                                  author_roles=(h.MEMBER_ROLE_ID,))
        since = len(h.CALLS)
        bot.dispatch("message", message)
        await h.settle(idle=0.8, maximum=6)
        return h.visible_text([c for c in h.CALLS[since:] if c[1] == f"/channels/{h.LOGCID}/messages"])

    shown = await post(LINK, h.TARGET_ID)
    check("**Mémoire :** 1er incident AutoMod en 30 j" in shown, "premier incident : « 1er incident AutoMod en 30 j »",
          shown[-260:])
    check("sur le serveur depuis" in shown, "la mémoire AutoMod reprend le contexte du membre", shown[-260:])

    # La carte telle que la voit le staff : le message supprimé, le nombre, la vraie
    # sanction — perdus auparavant (« action » attrapait « Infractions »).
    check("> regarde ça https://exemple-douteux.example/offre" in shown, "le message supprimé figure sur la carte",
          shown[-300:])
    check("Messages supprimés : **1**" in shown and "Sanction : **Suppression du message**" in shown
          and "Infractions (1h) : 1" in shown, "nombre de messages, sanction réelle et infractions sont affichés",
          shown[-300:])

    shown = await post(INVITE, h.TARGET_ID)
    check("2e incident AutoMod en 30 j (1 invitation, 1 lien)" in shown,
          "deuxième incident : le rang et les types sont rappelés", shown[-260:])

    since = len(h.CALLS)
    await asyncio.wait_for(h.run_prefix(bot, guild, f"+warn <@{h.TARGET_ID}> liens répétés", **MOD), 15)
    await h.settle(idle=0.4, maximum=3)
    shown = await post(LINK, h.TARGET_ID)
    check("3e incident AutoMod en 30 j (2 liens, 1 invitation)" in shown and "1 sanction en 30 j" in shown,
          "après un avertissement du staff : l'incident suivant le rappelle", shown[-260:])

    shown = await post(LINK, h.SECOND_ID)
    check("1er incident AutoMod en 30 j" in shown, "les incidents d'un autre membre ne sont pas mélangés", shown[-260:])

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
