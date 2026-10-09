#!/usr/bin/env python3
"""Le fil SentriX sur le bot booté : une action du staff = une référence, partout la même.

    python3 tools/trace_e2e.py
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

ADMIN = dict(author_id=h.ADMIN_ID, author_roles=(h.ADMIN_ROLE_ID,))
MEMBER = dict(author_id=h.TARGET_ID, author_roles=(h.MEMBER_ROLE_ID,))
REF = re.compile(r"Réf\. (SX-[0-9A-Z]{7})")


def texts(since: int, channel_id: int | None = None) -> str:
    calls = h.CALLS[since:]
    if channel_id is not None:
        calls = [c for c in calls if c[1] == f"/channels/{channel_id}/messages"]
    return h.visible_text(calls)


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    db = bot.db

    async def prefix(command: str, who: dict) -> int:
        since = len(h.CALLS)
        await asyncio.wait_for(h.run_prefix(bot, guild, command, **who), 15)
        await h.settle(idle=0.4, maximum=3)
        return since

    async def rows():
        return [dict(r) for r in await db.fetchall("SELECT * FROM sentrix_traces ORDER BY created_at, rowid")]

    check(bot.get_cog("Trace") is not None, "le cog Trace est chargé")
    # La fenêtre anti-doublon (Moderation.SANCTION_DUPLICATE_TTL, 6 s) refuse une
    # seconde sanction trop proche sur le même membre : voulu en production, mais
    # le scénario enchaîne volontairement +warn puis /warn sur la même cible.
    bot.get_cog("Moderation").SANCTION_DUPLICATE_TTL = 0

    # 1 — Une sanction : référence sur la réponse, la même sur la carte de log, une ligne exacte.
    since = await prefix(f"+warn <@{h.SECOND_ID}> spam répété", ADMIN)
    reply = texts(since, h.CID)
    log = texts(since, h.LOGCID)
    found = REF.search(reply)
    check(found is not None, "+warn : la réponse porte sa référence", reply[-160:])
    ref = found.group(1) if found else ((await rows()) or [{}])[-1].get("ref", "")
    check(bool(ref) and ref in log, "+warn : la carte de log porte LA MÊME référence", log[-200:])
    row = (await rows())[-1] if await rows() else {}
    check(row.get("ref") == ref and row.get("command") == "warn" and row.get("outcome") == "ok"
          and row.get("actor_id") == h.ADMIN_ID and row.get("target_id") == h.SECOND_ID
          and row.get("transport") == "prefix",
          "+warn : la trace dit qui, quoi, sur qui, avec quel résultat", str(row))

    # 2 — Une tentative refusée est tracée, sans référence affichée au curieux.
    before = len(await rows())
    since = await prefix(f"+ban <@{h.SECOND_ID}> test", MEMBER)
    after = await rows()
    check(len(after) == before + 1 and after[-1]["outcome"] == "refusé" and after[-1]["actor_id"] == h.TARGET_ID,
          "un +ban refusé à un membre est tracé comme refusé", str(after[-1] if after else None))
    check("Réf." not in texts(since), "le refus n'affiche pas de référence")

    # 3 — Une commande publique n'est ni tracée ni signée.
    before = len(await rows())
    since = await prefix("+ping", MEMBER)
    check(len(await rows()) == before and "Réf." not in texts(since), "+ping : ni trace ni référence")

    # 4 — Slash : même fil.
    since = len(h.CALLS)
    inter = h.build_interaction(bot, "warn", [{"name": "member", "type": 6, "value": str(h.SECOND_ID)},
                                              {"name": "reason", "type": 3, "value": "flood"}], **ADMIN)
    await asyncio.wait_for(bot.tree._call(inter), 15)
    await h.settle(idle=0.4, maximum=3)
    slash_ref = REF.search(texts(since))
    last = (await rows())[-1]
    check(slash_ref is not None and last["ref"] == slash_ref.group(1) and last["transport"] == "slash",
          "/warn : référence affichée et trace slash", str(last))

    # 4 bis — La mémoire : la troisième sanction rappelle les deux premières et l'ancienneté.
    since = await prefix(f"+warn <@{h.SECOND_ID}> encore", ADMIN)
    reply = texts(since, h.CID)
    check("3 sanctions en 30 j" in reply and "sur le serveur depuis" in reply and REF.search(reply),
          "3e avertissement : la réponse rappelle 3 sanctions en 30 j et l'ancienneté", reply[-200:])
    cards = [c for c in h.CALLS[since:] if c[1] == f"/channels/{h.LOGCID}/messages"]
    check(len(cards) == 1, "3e avertissement en quelques secondes : sa carte de log part quand même",
          f"{len(cards)} carte(s)")
    since = await prefix(f"+giverole <@{h.SECOND_ID}> <@&{h.PING_ROLE_ID}>", ADMIN)
    reply = texts(since, h.CID)
    check(REF.search(reply) is not None and "sanction" not in reply,
          "+giverole : référence, mais pas de compte de sanctions (ce n'est pas une sanction)", reply[-200:])

    # 5 — +trace reconstitue l'action ; /logs trace accepte une saisie approximative.
    since = await prefix(f"+trace {ref}", ADMIN)
    shown = texts(since)
    check(f"Trace {ref}" in shown and f"<@{h.SECOND_ID}>" in shown and "Exécutée" in shown and "+warn" in shown,
          "+trace : qui, quoi, sur qui, résultat", shown[:240])
    since = len(h.CALLS)
    inter = h.build_interaction(bot, "logs", [{"name": "trace", "type": 1, "options": [
        {"name": "reference", "type": 3, "value": ref.lower().replace("-", " ")}]}], **ADMIN)
    await asyncio.wait_for(bot.tree._call(inter), 15)
    await h.settle(idle=0.4, maximum=3)
    check(f"Trace {ref}" in texts(since), "/logs trace : retrouve « sx 7k… » écrit en minuscules", texts(since)[:200])

    # 6 — Un membre ne lit pas les traces.
    since = await prefix(f"+trace {ref}", MEMBER)
    check("Voir les logs du serveur" in texts(since) and f"Trace {ref}" not in texts(since),
          "membre : +trace refusé (Voir les logs du serveur)", texts(since)[:160])

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
