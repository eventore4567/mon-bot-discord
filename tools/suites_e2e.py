#!/usr/bin/env python3
"""Les suites SentriX : sous une sanction, les gestes logiques d'après, en boutons.

Un bouton n'est qu'une commande pré-remplie, exécutée au nom de celui qui clique :
même décision de permission, même hiérarchie, même log, sa propre référence.

    python3 tools/suites_e2e.py
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
from suggestions_e2e import RESULTS, _buttons, check, click  # noqa: E402

ADMIN = dict(author_id=h.ADMIN_ID, author_roles=(h.ADMIN_ROLE_ID,))


def ids_in(since: int, channel_id: int) -> list[str]:
    found = []
    for m, p, js in h.CALLS[since:]:
        if m == "POST" and p == f"/channels/{channel_id}/messages":
            found += [b.get("custom_id", "") for b in _buttons({"components": (js or {}).get("components", [])})]
    return found


def ids_anywhere(since: int) -> list[str]:
    found = []
    for m, p, js in h.CALLS[since:]:
        data = (js or {}).get("data") if isinstance((js or {}).get("data"), dict) else (js or {})
        if isinstance(data, dict):
            found += [b.get("custom_id", "") for b in _buttons({"components": data.get("components", [])})]
    return found


def timeouts(since: int, user_id: int) -> list:
    return [js.get("communication_disabled_until") for m, p, js in h.CALLS[since:]
            if m == "PATCH" and p == f"/guilds/{h.GID}/members/{user_id}" and isinstance(js, dict)
            and "communication_disabled_until" in js]


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    bot.get_cog("Moderation").SANCTION_DUPLICATE_TTL = 0

    # 1 — Un avertissement propose ses suites.
    since = len(h.CALLS)
    await asyncio.wait_for(h.run_prefix(bot, guild, f"+warn <@{h.SECOND_ID}> spam", **ADMIN), 15)
    await h.settle(idle=0.4, maximum=3)
    ids = ids_in(since, h.CID)
    history = next((i for i in ids if ":history:" in i), None)
    timeout = next((i for i in ids if ":timeout:" in i), None)
    check(history is not None and timeout is not None and f":{h.SECOND_ID}:SX-" in timeout,
          "+warn : boutons Historique et Exclure 10 min, liés au membre et à la référence", str(ids))

    # 2 — Un simple membre clique « Exclure 10 min » : même refus que s'il avait tapé la commande.
    since = await click(bot, timeout or "", h.next_id(), "membre")
    await h.settle(idle=0.4, maximum=3)
    check(not timeouts(since, h.SECOND_ID), "un membre qui clique n'exclut personne")
    check("accès" in h.visible_text(h.CALLS[since:]), "il reçoit le refus de permission", h.visible_text(h.CALLS[since:])[:160])

    # 3 — L'administrateur clique : l'exclusion part, tracée comme un geste par bouton.
    since = await click(bot, timeout or "", h.next_id(), "admin")
    await h.settle(idle=0.6, maximum=4)
    check(any(timeouts(since, h.SECOND_ID)), "l'administrateur qui clique exclut le membre 10 min", str(timeouts(since, h.SECOND_ID)))
    row = await bot.db.fetchone("SELECT command, transport, outcome, actor_id, target_id, detail FROM sentrix_traces "
                                "ORDER BY created_at DESC, rowid DESC LIMIT 1")
    check(row is not None and row["command"] == "mute" and row["transport"] == "bouton" and row["outcome"] == "ok"
          and row["actor_id"] == h.ADMIN_ID and row["target_id"] == h.SECOND_ID,
          "trace : mute, par bouton, par l'administrateur, sur le membre", str(dict(row) if row else None))
    origin = (timeout or "").rsplit(":", 1)[-1]
    check(row is not None and row["detail"] == f"suite de {origin}",
          "la trace de l'exclusion note l'avertissement dont elle est la suite", str(dict(row) if row else None))
    logs = [c for c in h.CALLS[since:] if c[1] == f"/channels/{h.LOGCID}/messages"]
    check(len(logs) == 1, "l'exclusion par bouton a sa carte de log", f"{len(logs)} carte(s)")
    flags = [((js or {}).get("data") or {}).get("flags") for m, p, js in h.CALLS[since:] if p.endswith("/callback")]
    check(any((f or 0) & 64 for f in flags), "la réponse au clic est privée (éphémère)", str(flags))

    # 3 bis — La confirmation de l'exclusion propose à son tour « Lever l'exclusion ».
    lift = next((i for i in ids_anywhere(since) if ":untimeout:" in i), None)
    check(lift is not None, "la confirmation de l'exclusion propose « Lever l'exclusion »", str(ids_anywhere(since)))
    since = await click(bot, lift or "", h.next_id(), "admin")
    await h.settle(idle=0.6, maximum=4)
    check(None in timeouts(since, h.SECOND_ID), "« Lever l'exclusion » lève réellement l'exclusion", str(timeouts(since, h.SECOND_ID)))

    # 3 ter — Bannissement puis « Débannir ».
    since = len(h.CALLS)
    await asyncio.wait_for(h.run_prefix(bot, guild, f"+ban <@{h.SECOND_ID}> raid", **ADMIN), 15)
    await h.settle(idle=0.6, maximum=4)
    unban = next((i for i in ids_anywhere(since) if ":unban:" in i), None)
    check(unban is not None, "+ban : bouton « Débannir »", str(ids_anywhere(since)))
    since = await click(bot, unban or "", h.next_id(), "admin")
    await h.settle(idle=0.6, maximum=4)
    check(any(m == "DELETE" and p == f"/guilds/{h.GID}/bans/{h.SECOND_ID}" for m, p, _ in h.CALLS[since:]),
          "« Débannir » lève réellement le bannissement")

    # 4 — Historique : le dossier du membre, en privé.
    since = await click(bot, history or "", h.next_id(), "admin")
    await h.settle(idle=0.4, maximum=3)
    shown = h.visible_text(h.CALLS[since:])
    check("Avertissement" in shown or "avertissement" in shown, "Historique montre le dossier du membre", shown[:200])

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
