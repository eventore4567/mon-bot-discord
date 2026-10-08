#!/usr/bin/env python3
"""Les rappels partent vraiment, sur le bot booté comme en production.

Depuis le premier commit, /remind enregistrait le rappel et annonçait « Rappel
défini dans 10 min »… sans qu'aucun code ne l'envoie jamais (mesuré le
08/10/2026). Ce scénario rejoue la création en + et en /, avance l'horloge en
base, fait tourner la boucle de livraison et regarde ce qui part.

    python3 tools/reminders_e2e.py
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

MEMBER = dict(author_id=h.TARGET_ID, author_roles=(h.MEMBER_ROLE_ID,))
DM_CHANNEL = "100000000000009001"


def posts(since: int, channel_id) -> list[dict]:
    return [js or {} for m, p, js in h.CALLS[since:] if m == "POST" and p == f"/channels/{channel_id}/messages"]


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    cog = bot.get_cog("Utility")
    db = bot.db
    check(bot.get_command("remind").callback.__module__ == "cogs.utility", "+remind est celle de cogs.utility")
    check(cog.deliver_reminders.is_running(), "la boucle de livraison tourne")

    async def fire() -> int:
        await db.execute("UPDATE reminders SET trigger_at = trigger_at - 7200")
        since = len(h.CALLS)
        await cog.deliver_reminders.coro(cog)
        await h.settle(idle=0.4, maximum=3)
        return since

    # 1 — Préfixe : le rappel part dans le salon, ne fait sonner que son auteur.
    await asyncio.wait_for(h.run_prefix(bot, guild, "+remind 10m sortir le chien @everyone", **MEMBER), 15)
    await h.settle(idle=0.3, maximum=2)
    check(await db.fetchone("SELECT 1 FROM reminders WHERE user_id=?", (h.TARGET_ID,)) is not None, "+remind enregistre le rappel")
    since = await fire()
    sent = [p for p in posts(since, h.CID) if "sortir le chien" in h.visible_text([("POST", "x", p)])]
    check(len(sent) == 1, "le rappel arrivé à échéance est envoyé une fois", str(len(sent)))
    allowed = (sent[0].get("allowed_mentions") or {}) if sent else {}
    check([str(u) for u in allowed.get("users", [])] == [str(h.TARGET_ID)] and "everyone" not in allowed.get("parse", []),
          "seul l'auteur est notifié, jamais @everyone écrit dans le rappel", str(allowed))
    check(sent and "Prévu" in h.visible_text([("POST", "x", sent[0])]), "un rappel en retard le dit")
    check(await db.fetchone("SELECT 1 FROM reminders WHERE user_id=?", (h.TARGET_ID,)) is None, "le rappel envoyé est retiré")
    since = await fire()
    check(not posts(since, h.CID), "un second passage ne renvoie rien")

    # 2 — Slash : même chemin.
    inter = h.build_interaction(bot, "remind", [{"name": "set", "type": 1, "options": [
        {"name": "duration", "type": 3, "value": "5m"}, {"name": "text", "type": 3, "value": "appeler maman"}]}], **MEMBER)
    await asyncio.wait_for(bot.tree._call(inter), 15)
    await h.settle(idle=0.3, maximum=2)
    since = await fire()
    check(any("appeler maman" in h.visible_text([("POST", "x", p)]) for p in posts(since, h.CID)),
          "/remind set : le rappel part aussi")

    # 3 — Annulé avant l'échéance : rien ne part.
    await asyncio.wait_for(h.run_prefix(bot, guild, "+remind 10m rien du tout", **MEMBER), 15)
    await h.settle(idle=0.3, maximum=2)
    row = await db.fetchone("SELECT id FROM reminders WHERE user_id=?", (h.TARGET_ID,))
    await asyncio.wait_for(h.run_prefix(bot, guild, f"+reminder-cancel {row['id']}", **MEMBER), 15)
    await h.settle(idle=0.3, maximum=2)
    since = await fire()
    check(not any("rien du tout" in h.visible_text([("POST", "x", p)]) for p in posts(since, h.CID)),
          "un rappel annulé ne part pas")

    # 4 — Rappel très en retard (créé avant que la livraison existe) : en privé, pas dans le salon.
    await db.execute(
        "INSERT INTO reminders (user_id, channel_id, guild_id, text, trigger_at, created_at) VALUES (?,?,?,?,?,?)",
        (h.TARGET_ID, h.CID, h.GID, "vieux rappel d'août", 1754000000, 1754000000),
    )
    since = await fire()
    check(not any("vieux rappel" in h.visible_text([("POST", "x", p)]) for p in posts(since, h.CID))
          and any("vieux rappel" in h.visible_text([("POST", "x", p)]) for p in posts(since, DM_CHANNEL)),
          "rappel en retard de plus de 24 h : en privé, jamais dans le salon")

    # 5 — Salon disparu : le rappel part en message privé.
    await db.execute(
        "INSERT INTO reminders (user_id, channel_id, guild_id, text, trigger_at, created_at) VALUES (?,?,?,?,?,?)",
        (h.TARGET_ID, 999999999999999999, h.GID, "salon supprimé", 0, 0),
    )
    since = await fire()
    check(any("salon supprimé" in h.visible_text([("POST", "x", p)]) for p in posts(since, DM_CHANNEL)),
          "salon disparu : le rappel part en message privé")

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
