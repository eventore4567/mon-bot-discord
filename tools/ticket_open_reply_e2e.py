#!/usr/bin/env python3
"""Ouvrir un ticket ne touche JAMAIS au panneau public (Jayden, 27/10/2026).

Avant : le panneau était remplacé par une grande carte « Ticket #11 créé » —
plus personne ne pouvait ouvrir de ticket depuis ce message. On vérifie sur le
bot booté qu'un membre qui choisit une catégorie reçoit UNE phrase éphémère avec
la vraie mention du salon, et que le message du panneau n'est pas modifié.

    python3 tools/ticket_open_reply_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402
import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import _base  # noqa: E402
from ticket_category_pick_e2e import _selects  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), label))
    print(("OK   " if ok else "ÉCHEC ") + label + (f" — {detail}" if detail and not ok else ""))


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    from cogs import setup_v2_core as core
    await core.set_module_enabled(bot, h.GID, "tickets", True, actor_id=h.ADMIN_ID)
    tickets = bot.get_cog("Tickets")
    panel_id = await tickets.create_panel(h.GID, "Support")
    type_id = await tickets.add_type(h.GID, panel_id, "Aide")
    await bot.db.execute("UPDATE ticket_panels_v2 SET channel_id = ?, enabled = 1 WHERE id = ?", (h.CID, panel_id))

    since = len(h.CALLS)
    await asyncio.wait_for(h.run_prefix(bot, guild, "+ticket", author_id=h.TARGET_ID,
                                        author_roles=(h.MEMBER_ROLE_ID,)), 20)
    await h.settle(idle=0.3, maximum=3)
    menus = _selects(h.CALLS[since:])
    check(bool(menus), "+ticket affiche le menu des catégories", str(h.visible_text(h.CALLS[since:]))[:200])
    if not menus:
        return 1
    menu = menus[0]
    panel_message_id = h.STATE["msg_seq"]
    values = [o["value"] for o in menu.get("options", [])]

    for tour, membre in enumerate((h.TARGET_ID, h.TARGET_ID + 7)):
        since = len(h.CALLS)
        data = _base(membre, (h.MEMBER_ROLE_ID,), kind=3,
                     data={"custom_id": menu["custom_id"], "component_type": 3, "values": values[:1]},
                     message=h.message_payload(panel_message_id, h.CID, ""))
        bot._connection._view_store.dispatch_view(3, menu["custom_id"], discord.Interaction(data=data, state=bot._connection))
        await h.settle(idle=0.6, maximum=8)
        calls = h.CALLS[since:]
        crees = [js for m, p, js in calls if m == "POST" and p.endswith("/channels") and isinstance(js, dict)]
        ecrase = [p for m, p, js in calls if m == "PATCH" and (p.endswith("/messages/@original")
                  or p.endswith(f"/messages/{panel_message_id}")) and "Ticket #" in json.dumps(js, ensure_ascii=False)]
        textes = [(js.get("content") or "") + h.visible_text([(m, p, js)]) for m, p, js in calls
                  if m == "POST" and "/webhooks/" in p and isinstance(js, dict)]
        prives = [js for m, p, js in calls if m == "POST" and "/webhooks/" in p and isinstance(js, dict)
                  and int(js.get("flags") or 0) & 64]
        textes += [((js.get("data") or {}).get("content") or "") for m, p, js in calls
                   if m == "POST" and p.endswith("/callback") and isinstance(js, dict)]
        reponse = next((t for t in textes if "Votre ticket a bien été ouvert" in t), "")
        check(bool(crees), f"membre {tour + 1} : salon du ticket créé", json.dumps([p for m, p, _ in calls])[:300])
        check(not ecrase, f"membre {tour + 1} : le panneau public n'est pas remplacé", str(ecrase)[:200])
        check(bool(prives), f"membre {tour + 1} : la confirmation est éphémère")
        check("Votre ticket a bien été ouvert : <#" in reponse,
              f"membre {tour + 1} : une phrase éphémère avec la vraie mention du salon", str(textes)[:300])

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except BaseException:
        import traceback
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)
