#!/usr/bin/env python3
"""La mémoire des tickets : prendre un ticket = savoir à qui l'on répond.

Rejoue la prise en charge réelle (Tickets.btn_claim, remplacé au démarrage par
cogs/ticket_claim_security.secure_claim) sur le bot booté.

    python3 tools/ticket_memory_e2e.py
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
from suggestions_e2e import RESULTS, _base, check  # noqa: E402


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    db = bot.db
    now = int(time.time())
    # Un ticket fermé il y a 4 jours, une sanction récente, puis le ticket en cours.
    await db.execute("INSERT INTO tickets (guild_id, channel_id, user_id, status, created_at) VALUES (?,?,?,?,?)",
                     (h.GID, 1, h.TARGET_ID, "ferme", now - 4 * 86400))
    await db.execute("INSERT INTO sanctions (guild_id, case_number, user_id, moderator_id, action, reason, created_at) "
                     "VALUES (?,?,?,?,?,?,?)", (h.GID, 1, h.TARGET_ID, h.MOD_ID, "warn", "spam", now - 3600))
    await db.execute("INSERT INTO tickets (guild_id, channel_id, user_id, status, created_at) VALUES (?,?,?,?,?)",
                     (h.GID, h.CID, h.TARGET_ID, "ouvert", now))
    ticket = await db.fetchone("SELECT * FROM tickets WHERE channel_id = ? AND status = 'ouvert'", (h.CID,))

    data = _base(h.ADMIN_ID, (h.ADMIN_ROLE_ID,), kind=3, data={"custom_id": "ticket_claim", "component_type": 2},
                 message=h.message_payload(h.next_id(), h.CID, ""))
    since = len(h.CALLS)
    await asyncio.wait_for(bot.get_cog("Tickets").btn_claim(discord.Interaction(data=data, state=bot._connection), ticket), 15)
    await h.settle(idle=0.4, maximum=3)

    if os.environ.get("SX_DEBUG"):
        for m, p, js in h.CALLS[since:]:
            print("CALL", m, p[:50], h.describe_call(m, p, js)[:300])
    claimed = await db.fetchone("SELECT claimed_by FROM tickets WHERE id = ?", (ticket["id"],))
    check(claimed["claimed_by"] == h.ADMIN_ID, "la prise en charge fonctionne toujours")
    # Le transport peut promouvoir le texte en panneau : on lit le texte VISIBLE.
    private = [js for m, p, js in h.CALLS[since:] if isinstance(js, dict)
               and "Avant de répondre" in h.visible_text([(m, p, js)])]
    check(len(private) == 1, "un seul message « Avant de répondre »", str(len(private)))
    note = h.visible_text([("POST", "x", private[0])]) if private else ""
    check("1 ticket avant celui-ci" in note and "fermé" in note and "il y a 4 j" in note,
          "il rappelle le ticket précédent, son âge et son état", note)
    check("1 sanction en 30 j" in note and "sur le serveur depuis" in note, "il rappelle la sanction récente et l'ancienneté", note)
    flags = int((private[0].get("flags") or 0)) if private else 0
    check(bool(flags & 64), "le rappel est privé (éphémère) : le membre ne lit pas son dossier", str(flags))
    mentions = (private[0].get("allowed_mentions") or {}) if private else {}
    check(private and "everyone" not in mentions.get("parse", []) and "roles" not in mentions.get("parse", []),
          "le rappel ne fait sonner ni @everyone ni rôle (et, éphémère, personne d'autre ne le voit)", str(mentions))

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
