#!/usr/bin/env python3
"""La liste des serveurs du dashboard, par le vrai gestionnaire servi.

Règle (web/admin_only_dashboard) : SentriX présent ET l'utilisateur propriétaire
ou Administrateur. Plainte d'un admin (10/10/2026) : des serveurs manquaient, et
la liste montrait des serveurs sans SentriX ou où il n'était pas admin.

    python3 tools/dashboard_guilds_e2e.py
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
from suggestions_e2e import RESULTS, check  # noqa: E402

G_MEMBRE = 200000000000000001   # SentriX présent, l'utilisateur simple membre
G_PANNE = 200000000000000002    # SentriX présent, Discord ne répond pas pour le membre
G_SANS_BOT = 200000000000000003  # l'utilisateur admin, SentriX absent
ADMIN_PERMS = str(discord.Permissions(administrator=True).value)


def add_guild(bot, guild_id: int, name: str, members: list[dict]) -> discord.Guild:
    state = bot._connection
    roles = [{"id": str(guild_id), "name": "@everyone", "permissions": "0", "position": 0, "color": 0,
              "hoist": False, "managed": False, "mentionable": False}]
    data = {
        "id": str(guild_id), "name": name, "owner_id": str(h.AUTHOR_ID), "roles": roles, "channels": [],
        "members": members, "emojis": [], "features": [], "afk_timeout": 300, "verification_level": 0,
        "default_message_notifications": 0, "explicit_content_filter": 0, "mfa_level": 0, "premium_tier": 0,
        "preferred_locale": "fr", "nsfw_level": 0, "stickers": [], "large": True, "member_count": 50,
        "system_channel_flags": 0, "premium_progress_bar_enabled": False, "voice_states": [],
    }
    guild = discord.Guild(data=data, state=state)
    state._add_guild(guild)
    for payload in members:
        guild._add_member(discord.Member(data=payload, guild=guild, state=state))
    return guild


async def main() -> int:
    from aiohttp.test_utils import make_mocked_request

    from web import dashboard

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    add_guild(bot, G_MEMBRE, "Serveur où je suis membre", [h.member_payload(h.ADMIN_ID, "admin", [])])
    add_guild(bot, G_PANNE, "Serveur où Discord ne répond pas", [])
    # Discord ne répond pas pour les membres de ce serveur (503), comme une panne passagère.
    from discord.http import HTTPClient, Route

    real_request = HTTPClient.request

    async def flaky(self, route, *args, **kwargs):
        if route.url.replace(Route.BASE, "").startswith(f"/guilds/{G_PANNE}/members/"):
            raise discord.HTTPException(type("R", (), {"status": 503, "reason": "Unavailable"})(), "indisponible")
        return await real_request(self, route, *args, **kwargs)

    HTTPClient.request = flaky
    web_app = dashboard.build_app(bot)
    handler = next(route.handler for route in web_app.router.routes()
                   if route.method == "GET" and getattr(route.resource, "canonical", "") == "/api/guilds")

    async def listed(user_id: int, oauth: list[dict]) -> list[str]:
        session = {"user": {"id": str(user_id)}, "guilds": oauth, "csrf": "x"}
        dashboard._require_session = lambda request: (session, None)
        dashboard._session = lambda request: session
        request = make_mocked_request("GET", "/api/guilds", app={"bot": bot, "sessions": {}})
        response = await handler(request)
        return [g["name"] for g in json.loads(response.body)["guilds"]]

    oauth_admin = [
        {"id": str(h.GID), "name": "Serveur test", "owner": False, "access_level": "administrator"},
        {"id": str(G_SANS_BOT), "name": "Serveur sans SentriX", "owner": False, "access_level": "administrator"},
        {"id": str(G_MEMBRE), "name": "Serveur où je suis membre", "owner": False, "access_level": "manage_guild"},
        {"id": str(G_PANNE), "name": "Serveur où Discord ne répond pas", "owner": False, "access_level": "administrator"},
    ]
    names = await listed(h.ADMIN_ID, oauth_admin)
    check("Serveur test" in names, "le serveur où je suis admin et où SentriX est présent est listé", str(names))
    check("Serveur sans SentriX" not in names, "un serveur sans SentriX n'est plus listé", str(names))
    check("Serveur où je suis membre" not in names, "un serveur où je ne suis pas admin n'est plus listé", str(names))
    check("Serveur où Discord ne répond pas" in names,
          "si Discord ne répond pas, la connexion (admin au login) fait foi : le serveur ne disparaît pas", str(names))

    oauth_manager = [dict(item, access_level="manage_guild") if item["id"] == str(G_PANNE) else item for item in oauth_admin]
    names = await listed(h.ADMIN_ID, oauth_manager)
    check("Serveur où Discord ne répond pas" not in names,
          "…mais pas si la connexion ne le disait pas admin (aucun accès accordé par défaut)", str(names))

    session = {"user": {"id": str(h.ADMIN_ID)}, "guilds": oauth_admin, "csrf": "x"}
    dashboard._require_session = lambda request: (session, None)
    response = await handler(make_mocked_request("GET", "/api/guilds", app={"bot": bot, "sessions": {}}))
    check(str(json.loads(response.body).get("invite_url") or "").startswith("https://"),
          "le lien « Ajouter SentriX » reste fourni (bouton + du dashboard)", str(json.loads(response.body).get("invite_url")))

    names = await listed(h.AUTHOR_ID, [])
    check("Serveur test" in names, "le propriétaire voit son serveur", str(names))
    names = await listed(h.SECOND_ID, [])
    check(names == [], "un simple membre ne voit aucun serveur", str(names))

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
