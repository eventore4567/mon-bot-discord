#!/usr/bin/env python3
"""Majuscules et émojis : message retiré, AUCUNE sanction, sur le bot booté.

24/11/2026 : « pour les majuscules et les trucs pas graves, fais que ça
supprime sans sanction ». Revue Codex (PR #723) : « antiemoji » est aussi un
filtre de spam ; l'escalade de spam l'avertissait ou le mutait quand même.

    python3 tools/petites_fautes_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402

FAUTIF = 100000000000008001


async def main() -> int:
    bot = await h.boot(quiet=True)
    automod_module = sys.modules["cogs.automod"]
    automod_module.INCIDENT_LOG_DELAY_SECONDS = 0.1
    guild = await h.setup_world(bot)
    automod = bot.get_cog("Automod")
    await bot.db.execute("INSERT INTO automod_settings (guild_id) VALUES (?) ON CONFLICT(guild_id) DO NOTHING", (h.GID,))
    await bot.db.execute("UPDATE automod_settings SET anticaps=1, antiemoji=1, antispam=0 WHERE guild_id=?", (h.GID,))
    automod.automod_cache.clear()

    appels = {"spam": 0, "escalade": 0}
    spam_orig, escalade_orig = automod._spam_progressive_action, automod._maybe_escalate

    async def spam_espion(*a, **k):
        appels["spam"] += 1
        return await spam_orig(*a, **k)

    async def escalade_espionne(*a, **k):
        appels["escalade"] += 1
        return await escalade_orig(*a, **k)

    automod._spam_progressive_action = spam_espion
    automod._maybe_escalate = escalade_espionne

    since = len(h.CALLS)
    ids = []
    textes = ["😀" * 12, "CECI EST UN MESSAGE ENTIEREMENT EN MAJUSCULES POUR TESTER", "🎉" * 15,
              "ENCORE UN MESSAGE TOUT EN MAJUSCULES QUI CRIE TRES FORT ICI"]
    for texte in textes:
        message = h.build_message(bot, guild, texte, author_id=FAUTIF, author_name="fautif",
                                  author_roles=(h.MEMBER_ROLE_ID,))
        ids.append(message.id)
        bot.dispatch("message", message)
        await h.settle(idle=0.4, maximum=4)
        automod.incidents.clear()  # chaque faute est une détection à part entière
    await h.settle(idle=0.6, maximum=6)

    supprimes = set()
    timeouts = []
    for method, path, js in h.CALLS[since:]:
        m = re.fullmatch(rf"/channels/{h.CID}/messages/(\d+)", path)
        if method == "DELETE" and m:
            supprimes.add(int(m.group(1)))
        if method == "PATCH" and path.endswith(f"/members/{FAUTIF}") and (js or {}).get("communication_disabled_until"):
            timeouts.append(js)
    check(all(i in supprimes for i in ids), "majuscules et émojis : chaque message est retiré",
          f"{len(supprimes & set(ids))}/{len(ids)}")
    check(appels["spam"] == 0 and appels["escalade"] == 0,
          "aucune escalade (ni avertissement compté, ni progression anti-spam)", str(appels))
    check(not timeouts, "aucune exclusion temporaire", str(timeouts)[:160])

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
