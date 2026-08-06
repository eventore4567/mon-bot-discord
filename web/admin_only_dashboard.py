"""Verrou global : le dashboard privé est réservé aux administrateurs Discord."""

from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger("bot.dashboard.admin-only")
_INSTALLED = False

_PRIVATE_PAGE_PATHS = {"/app", "/setup-center"}

ACCESS_DENIED_HTML = """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
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
    <p>Vous êtes connecté à Discord, mais vous ne pouvez pas utiliser le dashboard SentriX sans la permission <b>Administrateur</b> sur au moins un serveur concerné.</p>
    <div class="notice">Aucun réglage, aucune sanction, aucun log et aucun outil Setup ne sont accessibles tant que cette permission n'est pas accordée.</div>
    <p>Après avoir reçu la permission Administrateur, reconnectez-vous au dashboard pour actualiser vos serveurs.</p>
    <div class="actions"><a href="/?public=1">Voir la page publique</a><a class="primary" href="/login">Se reconnecter avec Discord</a></div>
  </main>
</body>
</html>"""


async def _refresh_admin_guilds(request: web.Request, dashboard, session: dict) -> bool:
    """Revérifie les permissions actuelles et retire les accès devenus invalides."""
    bot = request.app["bot"]
    try:
        user_id = int(session["user"]["id"])
    except (KeyError, TypeError, ValueError):
        return False

    verified: list[dict] = []
    for item in list(session.get("guilds", [])):
        try:
            guild_id = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue

        guild = bot.get_guild(guild_id)
        if guild is None:
            # Le bot n'est pas encore installé. Cette entrée provient du scope OAuth
            # `guilds`, déjà filtré sur propriétaire/Administrateur, et permet uniquement
            # d'afficher le bouton d'invitation — aucune configuration n'est accessible.
            verified.append(item)
            continue

        if await dashboard._administrator_member(guild, user_id) is not None:
            verified.append(item)

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

        # Connexion OAuth, état du bot, API publique et déconnexion restent accessibles.
        if (
            path in {"/health", "/login", "/oauth/callback", "/logout", "/api/public"}
            or request.method == "OPTIONS"
        ):
            return await handler(request)

        session = dashboard._session(request)

        # La racine sert de page publique quand personne n'est connecté. Avec une ancienne
        # session sans Administrateur, elle ne doit surtout pas réafficher le dashboard.
        if path == "/":
            if session is None or request.query.get("public") == "1":
                return await handler(request)
            if not await _refresh_admin_guilds(request, dashboard, session):
                return _denied_page()
            return await handler(request)

        # /api/me affiche uniquement l'identité connectée et ne donne accès à aucun serveur.
        if path == "/api/me":
            return await handler(request)

        needs_admin = path in _PRIVATE_PAGE_PATHS or path.startswith("/api/")
        if not needs_admin:
            return await handler(request)

        if session is None:
            if path in _PRIVATE_PAGE_PATHS:
                raise web.HTTPFound("/login")
            return dashboard._json_error("Connectez-vous avec Discord pour continuer.", 401)

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
        # Le middleware de sécurité existant reste en première position : il ajoute ses
        # en-têtes à toutes les réponses, y compris à la page « accès refusé ».
        app.middlewares.append(administrator_only)
        return app

    dashboard.build_app = build_app
    logger.info("Dashboard verrouillé : permission Administrateur obligatoire.")
