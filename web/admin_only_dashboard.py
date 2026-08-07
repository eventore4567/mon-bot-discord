"""Verrou global : le dashboard privé est réservé aux administrateurs Discord."""

from __future__ import annotations

import logging

from aiohttp import web

from utils.owner_access import is_bot_owner_id

logger = logging.getLogger("bot.dashboard.admin-only")
_INSTALLED = False

_PRIVATE_PAGE_PATHS = {"/app", "/setup-center"}

ACCESS_DENIED_HTML = """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#090b12">
  <title>SentriX — Accès refusé</title>
  <style>
    :root{color-scheme:dark;--bg:#090b12;--panel:#111522;--line:#29304a;--text:#f2f4ff;--muted:#9ca5bc;--brand:#7c6cff;--bad:#ff758b}
    *{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:radial-gradient(circle at 20% 0,#392d7255,transparent 36%),var(--bg);color:var(--text);font:16px Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
    main{width:min(620px,100%);padding:34px;background:var(--panel);border:1px solid var(--line);border-radius:22px;box-shadow:0 28px 80px #0008}.icon{width:58px;height:58px;display:grid;place-items:center;border-radius:17px;background:#3c1822;color:var(--bad);font-size:28px;margin-bottom:20px}h1{margin:0 0 12px;font-size:30px}p{margin:0;color:var(--muted);line-height:1.7}.notice{margin:22px 0;padding:15px 16px;border:1px solid #654052;background:#28161d;border-radius:13px;color:#ffc0ca}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:24px}a{display:inline-flex;align-items:center;justify-content:center;padding:11px 16px;border-radius:11px;border:1px solid var(--line);color:var(--text);text-decoration:none;font-weight:800;background:#171c2c}a.primary{background:linear-gradient(135deg,var(--brand),#5d4de1);border-color:transparent}
  </style>
</head>
<body>
  <main>
    <div class="icon">🔒</div>
    <h1>Permission Administrateur obligatoire</h1>
    <p>Vous êtes connecté à Discord, mais vous ne pouvez pas utiliser le dashboard SentriX sans la permission <b>Administrateur</b> sur au moins un serveur où SentriX est présent.</p>
    <div class="notice">Les permissions sont vérifiées en direct. Si Administrateur vient d'être ajouté, rechargez simplement la page.</div>
    <p>Aucun réglage, aucune sanction, aucun log et aucun outil Setup ne sont accessibles sans cette permission.</p>
    <div class="actions"><a href="/?public=1">Voir la page publique</a><a class="primary" href="/app">Réessayer</a></div>
  </main>
</body>
</html>"""


def _installed_item(guild, user_id: int, previous: dict | None = None) -> dict:
    """Construit l'entrée affichée sans dépendre de l'ancien snapshot OAuth."""
    icon_url = str(guild.icon.url) if getattr(guild, "icon", None) else None
    return {
        "id": str(guild.id),
        "name": guild.name,
        "icon_url": icon_url,
        "owner": guild.owner_id == user_id,
        **({k: v for k, v in (previous or {}).items() if k not in {"id", "name", "icon_url", "owner"}}),
    }


async def _refresh_admin_guilds(request: web.Request, dashboard, session: dict) -> bool:
    """Reconstruit les accès depuis Discord au lieu de garder le snapshot OAuth du login."""
    bot = request.app["bot"]
    try:
        user_id = int(session["user"]["id"])
    except (KeyError, TypeError, ValueError):
        return False

    previous_by_id: dict[int, dict] = {}
    oauth_only: list[dict] = []
    for item in list(session.get("guilds", [])):
        try:
            guild_id = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        previous_by_id[guild_id] = item
        if bot.get_guild(guild_id) is None:
            oauth_only.append(item)

    verified: list[dict] = []
    seen: set[int] = set()
    for guild in list(bot.guilds):
        if await dashboard._administrator_member(guild, user_id) is None:
            continue
        verified.append(_installed_item(guild, user_id, previous_by_id.get(guild.id)))
        seen.add(guild.id)

    for item in oauth_only:
        try:
            guild_id = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if guild_id not in seen:
            verified.append(item)
            seen.add(guild_id)

    session["guilds"] = verified
    return bool(verified)


def _denied_page() -> web.Response:
    return web.Response(
        text=ACCESS_DENIED_HTML,
        content_type="text/html",
        status=403,
        headers={"Cache-Control": "private, no-store"},
    )


def _denied_api(dashboard) -> web.Response:
    return dashboard._json_error(
        "Accès refusé : la permission Discord Administrateur est obligatoire pour utiliser le dashboard.",
        403,
    )


def _owner_session(session: dict | None) -> bool:
    return bool(session and is_bot_owner_id(session.get("user", {}).get("id")))


def install(dashboard) -> None:
    """Ajoute le contrôle après toutes les extensions, afin de couvrir leurs routes aussi."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_build_app = dashboard.build_app

    @web.middleware
    async def administrator_only(request: web.Request, handler):
        path = request.path

        if (
            path in {"/health", "/login", "/oauth/callback", "/logout", "/api/public"}
            or request.method == "OPTIONS"
        ):
            return await handler(request)

        session = dashboard._session(request)
        owner_mode = _owner_session(session)

        # Zone propriétaire : invisible aux autres et indépendante des permissions du
        # compte dans les serveurs. Cela permet notamment de retirer SentriX d'un serveur
        # même si le propriétaire du bot n'en est plus membre.
        if path == "/owner-servers" or path.startswith("/api/owner/"):
            if session is None:
                if path == "/owner-servers":
                    raise web.HTTPFound("/login")
                return dashboard._json_error("Connectez-vous avec Discord pour continuer.", 401)
            if not owner_mode:
                raise web.HTTPNotFound()
            return await handler(request)

        if path == "/":
            if session is None or request.query.get("public") == "1":
                return await handler(request)
            if owner_mode:
                return await handler(request)
            if not await _refresh_admin_guilds(request, dashboard, session):
                return _denied_page()
            return await handler(request)

        if path == "/api/me":
            return await handler(request)

        needs_admin = path in _PRIVATE_PAGE_PATHS or path.startswith("/api/")
        if not needs_admin:
            return await handler(request)

        if session is None:
            if path in _PRIVATE_PAGE_PATHS:
                raise web.HTTPFound("/login")
            return dashboard._json_error("Connectez-vous avec Discord pour continuer.", 401)

        # Le propriétaire du bot peut toujours ouvrir l'interface principale. Les routes
        # de configuration d'un serveur restent ensuite protégées par _manageable_guild,
        # donc ce bypass ne donne pas de droits de modération sur un serveur où il n'est
        # pas Administrateur.
        if owner_mode and path in _PRIVATE_PAGE_PATHS:
            return await handler(request)

        if not await _refresh_admin_guilds(request, dashboard, session):
            logger.warning(
                "Dashboard refusé à l'utilisateur %s sur %s : aucune permission Administrateur.",
                session.get("user", {}).get("id", "inconnu"),
                path,
            )
            return _denied_page() if path in _PRIVATE_PAGE_PATHS else _denied_api(dashboard)

        return await handler(request)

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app.middlewares.append(administrator_only)
        return app

    dashboard.build_app = build_app
    logger.info("Dashboard verrouillé : Administrateur requis, avec zone propriétaire séparée.")
