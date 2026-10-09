#!/usr/bin/env python3
"""Le journal des réglages sur le bot booté : chaque changement, d'où qu'il vienne, s'annule.

    python3 tools/config_journal_e2e.py
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
from suggestions_e2e import RESULTS, _base, _buttons, check, click  # noqa: E402
from welcome_e2e import control, setup_page  # noqa: E402

ADMIN = dict(author_id=h.ADMIN_ID, author_roles=(h.ADMIN_ROLE_ID,))


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    db = bot.db

    async def last_entry(field: str):
        row = await db.fetchone("SELECT * FROM config_journal WHERE guild_id=? AND field=? ORDER BY id DESC LIMIT 1",
                                (h.GID, field))
        return dict(row) if row else None

    # 1 — /setup : le salon de bienvenue changé par le vrai point de dispatch des menus.
    view = await setup_page(bot, guild, "welcome")
    select = control(view, lambda i: isinstance(i, discord.ui.ChannelSelect))
    data = _base(h.ADMIN_ID, (h.ADMIN_ROLE_ID,), kind=3, data={
        "custom_id": select.custom_id, "component_type": 8, "values": [str(h.LOGCID)],
        "resolved": {"channels": {str(h.LOGCID): {"id": str(h.LOGCID), "type": 0, "name": "logs",
                                                  "permissions": str(discord.Permissions.all().value)}}},
    }, message=h.message_payload(h.next_id(), h.CID, ""))
    await view._scheduled_task(select, discord.Interaction(data=data, state=bot._connection))
    await h.settle(idle=0.4, maximum=3)
    entry = await last_entry("welcome_channel")
    check(entry is not None and entry["old_value"] == str(h.CID) and entry["new_value"] == str(h.LOGCID)
          and entry["actor_id"] == h.ADMIN_ID and entry["source"] == "menu",
          "/setup : avant, après, auteur et canal journalisés", str(entry))
    welcome_entry = entry

    # 2 — Commande.
    await asyncio.wait_for(h.run_prefix(bot, guild, "+setprefix !", **ADMIN), 15)
    await h.settle(idle=0.3, maximum=2)
    entry = await last_entry("prefix")
    check(entry is not None and entry["new_value"] == "!" and entry["source"] == "prefix" and entry["actor_id"] == h.ADMIN_ID,
          "+setprefix : journalisé comme commande, avec son auteur", str(entry))
    first_prefix = entry

    # 3 — Dashboard : le middleware pose l'auteur de la session.
    # Le harnais coupe tout réseau sortant, localhost compris : on appelle le
    # middleware sur une requête aiohttp factice, comme le ferait le serveur.
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request

    from web import dashboard

    async def handler(_request):
        await db.set_guild_config(h.GID, "level_channel", h.LOGCID)
        return web.json_response({"ok": True})

    original_session = dashboard._require_session
    dashboard._require_session = lambda _request: ({"user": {"id": str(h.ADMIN_ID)}, "csrf": "x"}, None)
    try:
        await dashboard.config_actor(make_mocked_request("POST", "/api/guilds/1/config"), handler)
    finally:
        dashboard._require_session = original_session
    entry = await last_entry("level_channel")
    check(entry is not None and entry["source"] == "dashboard" and entry["actor_id"] == h.ADMIN_ID,
          "dashboard : journalisé avec la personne connectée", str(entry))

    # 4 — L'historique se lit, avec un bouton d'annulation par changement.
    since = len(h.CALLS)
    # Le préfixe du serveur est désormais « ! » (étape 2).
    await asyncio.wait_for(h.run_prefix(bot, guild, "!config-history", **ADMIN), 15)
    await h.settle(idle=0.3, maximum=2)
    shown = h.visible_text(h.CALLS[since:])
    labels = [b.get("custom_id") for m, p, js in h.CALLS[since:] if isinstance(js, dict)
              for b in _buttons({"components": js.get("components", [])})]
    check("Salon de bienvenue" in shown and f"<#{h.CID}> → <#{h.LOGCID}>" in shown and f"<@{h.ADMIN_ID}>" in shown,
          "+config-history : réglage, avant → après, auteur", shown[:240])
    check(f"sx:undo:{welcome_entry['id']}" in labels, "un bouton « Annuler » par changement", str(labels))

    # 5 — Un membre ne peut pas annuler.
    since = await click(bot, f"sx:undo:{welcome_entry['id']}", h.next_id(), "membre")
    conf = await db.get_guild_config(h.GID)
    check(conf["welcome_channel"] == h.LOGCID and "accès" in h.visible_text(h.CALLS[since:]),
          "membre : annulation refusée, réglage intact", h.visible_text(h.CALLS[since:])[:120])

    # 6 — L'administrateur annule : valeur d'avant remise, annulation journalisée et loguée.
    since = await click(bot, f"sx:undo:{welcome_entry['id']}", h.next_id(), "admin")
    await h.settle(idle=0.4, maximum=3)
    conf = await db.get_guild_config(h.GID)
    check(conf["welcome_channel"] == h.CID, "annulation : le salon de bienvenue redevient l'ancien")
    entry = await last_entry("welcome_channel")
    check(entry["source"] == "annulation" and entry["actor_id"] == h.ADMIN_ID, "l'annulation est elle-même journalisée", str(entry))
    logs = h.visible_text([c for c in h.CALLS[since:] if c[1] == f"/channels/{h.LOGCID}/messages"])
    check("Réglage annulé" in logs, "l'annulation a sa carte de log", logs[:160])
    since = await click(bot, f"sx:undo:{welcome_entry['id']}", h.next_id(), "admin")
    check("déjà été annulé" in h.visible_text(h.CALLS[since:]), "un changement ne s'annule qu'une fois")

    # 7 — On n'écrase jamais un changement plus récent.
    await asyncio.wait_for(h.run_prefix(bot, guild, "!setprefix ?", **ADMIN), 15)
    await h.settle(idle=0.3, maximum=2)
    since = await click(bot, f"sx:undo:{first_prefix['id']}", h.next_id(), "admin")
    conf = await db.get_guild_config(h.GID)
    check(conf["prefix"] == "?" and "modifié depuis" in h.visible_text(h.CALLS[since:]),
          "un ancien changement ne s'annule pas par-dessus un plus récent", h.visible_text(h.CALLS[since:])[:160])

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
