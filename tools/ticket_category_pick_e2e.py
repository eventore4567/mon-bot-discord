#!/usr/bin/env python3
"""Ouvrir un ticket quand le serveur a plusieurs panels : choisir la catégorie marche.

Production, 23/10/2026 (21:38 et 22:19) : « Action du panneau échouée title=🎫 Ouvrir
un ticket item=Select » — on_pick appelait Tickets.build_panel_embed, remplacé le
30/09 par build_public_panel. Chaque membre qui choisissait une catégorie restait
bloqué ; +create-server publiait son panel par le même chemin mort.

    python3 tools/ticket_category_pick_e2e.py
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
from suggestions_e2e import RESULTS, _base, check  # noqa: E402

MEMBRE = dict(author_id=h.TARGET_ID, author_roles=(h.MEMBER_ROLE_ID,))


def _selects(calls) -> list[dict]:
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == 3:
                found.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for _m, _p, js in calls:
        walk(js)
    return found


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    tickets = bot.get_cog("Tickets")
    ids = []
    for nom, type_ in (("Support", "Aide"), ("Partenariat", "Demande")):
        panel_id = await tickets.create_panel(h.GID, nom)
        await tickets.add_type(h.GID, panel_id, type_)
        await bot.db.execute("UPDATE ticket_panels_v2 SET channel_id = ?, enabled = 1 WHERE id = ?", (h.CID, panel_id))
        ids.append(panel_id)

    since = len(h.CALLS)
    await asyncio.wait_for(h.run_prefix(bot, guild, "+ticket", **MEMBRE), 20)
    await h.settle(idle=0.3, maximum=3)
    menus = _selects(h.CALLS[since:])
    check(len(menus) == 1 and len(menus[0].get("options", [])) == 2,
          "+ticket avec deux panels : un menu de deux catégories", str(menus)[:200])
    custom_id = menus[0]["custom_id"] if menus else ""

    errors: list[str] = []
    original = bot.get_cog("Tickets").__class__.__dict__.get("cog_app_command_error")
    since = len(h.CALLS)
    data = _base(h.TARGET_ID, (h.MEMBER_ROLE_ID,), kind=3,
                 data={"custom_id": custom_id, "component_type": 3, "values": [str(ids[1])]},
                 message=h.message_payload(h.STATE["msg_seq"], h.CID, ""))
    bot._connection._view_store.dispatch_view(3, custom_id, discord.Interaction(data=data, state=bot._connection))
    await h.settle(idle=0.4, maximum=3)
    shown = h.visible_text(h.CALLS[since:])
    raw = json.dumps([js for _m, _p, js in h.CALLS[since:]])
    check("Demande" in shown and ("Catégories disponibles" in shown or "Comment ça marche" in shown),
          "choisir « Partenariat » affiche son panel et ses catégories", shown[:200])
    check("erreur" not in shown.lower() and "build_panel_embed" not in raw,
          "aucune erreur au choix de la catégorie", shown[:160])
    check(original is None or not errors, "pas d'exception relevée")

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
