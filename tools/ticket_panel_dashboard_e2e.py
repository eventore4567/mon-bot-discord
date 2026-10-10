#!/usr/bin/env python3
"""Dashboard → Tickets → Panneaux → « Publier », sur le bot booté.

Mesuré en production le 10/10/2026 : chaque publication depuis le dashboard
finissait en erreur 500 (« 'Tickets' object has no attribute
'build_panel_embed' »). Ce scénario passe par le vrai gestionnaire servi.

    python3 tools/ticket_panel_dashboard_e2e.py
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

import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, _buttons, check  # noqa: E402


async def main() -> int:
    from aiohttp.test_utils import make_mocked_request

    from web import dashboard, dashboard_v62_dense

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    tickets = bot.get_cog("Tickets")
    panel_id = await tickets.create_panel(h.GID, "Support")
    await tickets.add_type(h.GID, panel_id, "Aide")
    await bot.db.execute("UPDATE ticket_panels_v2 SET channel_id = ? WHERE id = ?", (h.CID, panel_id))

    async def manageable(request, guild_id):
        return {"user": {"id": str(h.ADMIN_ID)}}, guild, None

    dashboard._manageable_guild = manageable
    dashboard._require_csrf = lambda request, session: None

    app = {"bot": bot, "dashboard_module": dashboard, "write_limits": {}}

    async def publish() -> tuple[int, dict, list]:
        app["write_limits"].clear()  # le limiteur (0,5 s entre deux écritures) n'est pas l'objet du test
        body = json.dumps({"action": "ticket_send", "panel_id": panel_id}).encode()
        request = make_mocked_request(
            "POST", f"/api/guilds/{h.GID}/v62", match_info={"guild_id": str(h.GID)},
            app=app, headers={"Content-Type": "application/json"},
        )

        async def read_json():
            return json.loads(body)

        request.json = read_json
        since = len(h.CALLS)
        response = await dashboard_v62_dense.handle_v62_post(request)
        await h.settle(idle=0.4, maximum=3)
        return response.status, json.loads(response.body), h.CALLS[since:]

    status, data, calls = await publish()
    posts = [js for m, p, js in calls if m == "POST" and p == f"/channels/{h.CID}/messages"]
    check(status == 200, "« Publier » depuis le dashboard ne renvoie plus d'erreur 500", f"{status} {data}")
    ids = [b.get("custom_id", "") for js in posts for b in _buttons({"components": (js or {}).get("components", [])})]
    selects = [c for js in posts for c in json.dumps(js or {}).split('"type": 3')[1:]]
    check(len(posts) == 1 and (ids or selects), "le panneau est publié dans le salon, avec de quoi ouvrir un ticket",
          f"{len(posts)} message(s), {ids[:3]}")
    row = await bot.db.fetchone("SELECT message_id, channel_id FROM ticket_panels_v2 WHERE id = ?", (panel_id,))
    check(row["message_id"] and int(row["channel_id"]) == h.CID, "le message publié est enregistré sur le panneau",
          str(dict(row)))

    status, data, calls = await publish()
    deletes = [p for m, p, _ in calls if m == "DELETE" and p.startswith(f"/channels/{h.CID}/messages/")]
    check(status == 200 and deletes, "republier remplace l'ancien message (comme le bouton Discord)", f"{status} {deletes}")

    # Activer un module incomplet depuis le dashboard : un refus expliqué, pas
    # une erreur 500 (production, 10/10/2026 — accueil et rôles automatiques).
    web_app = dashboard.build_app(bot)
    handler = next(
        route.handler for route in web_app.router.routes()
        if route.method == "POST" and getattr(route.resource, "canonical", "") == "/api/guilds/{guild_id}/modules"
    )
    from cogs import setup_v2_core as core

    await bot.db.set_guild_config(h.GID, "welcome_channel", None)
    await bot.db.execute("DELETE FROM module_settings WHERE guild_id = ? AND module = 'welcome'", (h.GID,))

    async def toggle(module: str, action: str):
        app["write_limits"].clear()
        body = json.dumps({"module": module, "action": action}).encode()
        request = make_mocked_request(
            "POST", f"/api/guilds/{h.GID}/modules", match_info={"guild_id": str(h.GID)},
            app={**app, **{k: v for k, v in web_app.items() if isinstance(k, str)}},
            headers={"Content-Type": "application/json"},
        )

        async def read_json():
            return json.loads(body)

        request.json = read_json
        response = await handler(request)
        return response.status, json.loads(response.body)

    status, data = await toggle("welcome", "enable")
    check(status == 400 and "salon de bienvenue" in json.dumps(data, ensure_ascii=False),
          "activer Bienvenue sans salon : refus expliqué (400), plus d'erreur 500", f"{status} {data}")
    await bot.db.set_guild_config(h.GID, "welcome_channel", h.CID)
    status, data = await toggle("welcome", "enable")
    check(status == 200 and await core.module_enabled(bot, h.GID, "welcome"),
          "une fois le salon choisi, le module s'active", f"{status} {data}")

    # /setup → Tickets → « Activer » sur un serveur sans catégorie ni panneau : le
    # refus doit dire quoi configurer (avant : « Une erreur est survenue… »).
    import discord
    from setup_sweep import build, controls, interaction

    await bot.db.set_guild_config(h.GID, "ticket_category", None)
    await bot.db.execute("DELETE FROM ticket_panels_v2 WHERE guild_id = ?", (h.GID,))
    await bot.db.execute("DELETE FROM module_settings WHERE guild_id = ? AND module = 'tickets'", (h.GID,))
    page = await build(bot, guild, "tickets")
    activer = next((i for i in controls(page) if isinstance(i, discord.ui.Button) and str(i.label) == "Activer"), None)
    since = len(h.CALLS)
    await page._scheduled_task(activer, interaction(bot))
    await h.settle(idle=0.4, maximum=3)
    shown = h.visible_text(h.CALLS[since:])
    check(activer is not None and "Configurez d’abord une catégorie" in shown and "Une erreur est survenue" not in shown
          and not await core.module_enabled(bot, h.GID, "tickets"),
          "/setup : activer les tickets sans catégorie explique quoi configurer", shown[:200])

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
