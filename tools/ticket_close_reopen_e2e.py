#!/usr/bin/env python3
"""Fermer, envoyer le MP de transcription, rouvrir un ticket — sur le bot booté.

27/10/2026 : le MP affichait le nom du salon comme sujet et « 0 min » pour un
ticket court ; la réouverture ne vérifiait pas que le bouton venait du salon du
ticket. Lancé deux fois : réouverture dans le bon salon, puis depuis un autre.

    python3 tools/ticket_close_reopen_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import subprocess
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


async def main():
    bot = await h.boot(quiet=True); guild = await h.setup_world(bot)
    from cogs import setup_v2_core as core
    await core.set_module_enabled(bot, h.GID, "tickets", True, actor_id=h.ADMIN_ID)
    tickets = bot.get_cog("Tickets")
    panel_id = await tickets.create_panel(h.GID, "Support")
    await tickets.add_type(h.GID, panel_id, "Aide")
    await bot.db.execute("UPDATE ticket_panels_v2 SET channel_id = ?, enabled = 1 WHERE id = ?", (h.CID, panel_id))
    since=len(h.CALLS)
    await h.run_prefix(bot, guild, "+ticket", author_id=h.TARGET_ID, author_roles=(h.MEMBER_ROLE_ID,))
    await h.settle(idle=0.3, maximum=3)
    menu=_selects(h.CALLS[since:])[0]
    since=len(h.CALLS)
    data=_base(h.TARGET_ID,(h.MEMBER_ROLE_ID,),kind=3,data={"custom_id":menu["custom_id"],"component_type":3,"values":[menu["options"][0]["value"]]},message=h.message_payload(h.STATE["msg_seq"],h.CID,""))
    bot._connection._view_store.dispatch_view(3, menu["custom_id"], discord.Interaction(data=data,state=bot._connection))
    await h.settle(idle=0.6, maximum=8)
    row = await bot.db.fetchone("SELECT id, channel_id FROM tickets WHERE guild_id=? ORDER BY id DESC LIMIT 1", (h.GID,))
    chan = int(row["channel_id"])
    # quelques messages dans le ticket
    ch = guild.get_channel(chan)
    since=len(h.CALLS)
    data=_base(h.ADMIN_ID,(h.ADMIN_ROLE_ID,),kind=3,data={"custom_id":"ticket_ctrl_close","component_type":2},message=h.message_payload(h.next_id(),chan,""))
    data["channel_id"]=str(chan); data["channel"]={"id":str(chan),"type":0,"guild_id":str(h.GID),"name":getattr(ch,"name","t")}
    bot._connection._view_store.dispatch_view(2, "ticket_ctrl_close", discord.Interaction(data=data,state=bot._connection))
    await h.settle(idle=0.8, maximum=10)
    modal = next(js["data"] for m,p,js in h.CALLS[since:] if isinstance(js, dict) and js.get("type")==9)
    field = modal["components"][0]["components"][0]["custom_id"]
    comps=[{"type":1,"components":[{"type":4,"custom_id":field,"value":"Demande résolue"}]}]
    since=len(h.CALLS)
    data=_base(h.ADMIN_ID,(h.ADMIN_ROLE_ID,),kind=5,data={"custom_id":modal["custom_id"],"components":comps},message=h.message_payload(h.next_id(),chan,""))
    data["channel_id"]=str(chan)
    bot._connection._view_store.dispatch_modal(modal["custom_id"], discord.Interaction(data=data,state=bot._connection), comps, {})
    await h.settle(idle=1.0, maximum=15)
    apres = h.CALLS[since:]
    textes = [(p, h.visible_text([(m, p, js)])) for m, p, js in apres if m == "POST" and "/messages" in p]
    carte = " ".join(t for p, t in textes if f"/channels/{chan}/messages" in p)
    mp = " ".join(t for p, t in textes if "/channels/100000000000009001/messages" in p)
    check(any(m == "PUT" and p == f"/channels/{chan}/permissions/{h.TARGET_ID}" for m, p, _ in apres),
          "fermeture : l'accès du demandeur au salon est retiré")
    check("Ticket #1 · Fermé" in carte and "Demande résolue" in carte, "fermeture : carte de clôture avec la raison", carte[:200])
    check("Transcription — TICKET-0001" in mp, "MP : « Transcription — TICKET-0001 »", mp[:200])
    check("**Sujet :** Aide" in mp, "MP : le sujet est la catégorie choisie, pas le nom du salon", mp[:300])
    check(" 0 min" not in mp and re.search(r"\b\d+ s\b", mp) is not None, "MP : une durée courte s'écrit en secondes", mp[:400])
    tid = int(row["id"])
    since=len(h.CALLS)
    inter_data=_base(h.ADMIN_ID,(h.ADMIN_ROLE_ID,),kind=3,data={"custom_id":f"sx_ticket_open:{tid}","component_type":2},message=h.message_payload(h.next_id(),chan,""))
    inter_data["channel_id"]=str(chan)
    if os.environ.get("BON_SALON"): inter_data["channel"]={"id":str(chan),"type":0,"guild_id":str(h.GID),"name":"ticket-cible"}
    inter=discord.Interaction(data=inter_data,state=bot._connection)
    store=bot._connection._view_store
    for pattern,item_cls in getattr(store,"_dynamic_items",{}).items():
        mt=pattern.fullmatch(f"sx_ticket_open:{tid}")
        if mt:
            item=await item_cls.from_custom_id(inter, discord.ui.Button(custom_id=f"sx_ticket_open:{tid}"), mt)
            if await item.interaction_check(inter): await item.callback(inter)
            break
    await h.settle(idle=1.0, maximum=10)
    st = await bot.db.fetchone("SELECT status FROM tickets WHERE id=?", (tid,))
    if os.environ.get("BON_SALON"):
        check(st["status"] == "ouvert", "réouverture dans le salon du ticket : rouvert")
        check(any(m == "PUT" and p == f"/channels/{chan}/permissions/{h.TARGET_ID}" for m, p, _ in h.CALLS[since:]),
              "réouverture : l'accès du demandeur est rendu sur le salon du ticket")
    else:
        check(st["status"] == "ferme" and not any(m == "PUT" for m, _p, _ in h.CALLS[since:]),
              "réouverture depuis un autre salon : refusée, aucune permission touchée")
    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    return 1 if failed else 0


if __name__ == "__main__":
    if not os.environ.get("_SX_TICKET_PASSE"):
        # Deux passes isolées (un bot booté chacune) : bon salon, puis autre salon.
        codes = []
        for bon in ("1", ""):
            env = dict(os.environ, _SX_TICKET_PASSE="1", BON_SALON=bon)
            codes.append(subprocess.run([sys.executable, __file__], env=env).returncode)
        sys.exit(1 if any(codes) else 0)
    try:
        code = asyncio.run(main())
    except BaseException:
        import traceback
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)
