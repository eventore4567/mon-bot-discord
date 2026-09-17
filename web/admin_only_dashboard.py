"""Verrou global : le dashboard privé est réservé aux administrateurs Discord."""

from __future__ import annotations

import logging
import time

import discord
from aiohttp import web

from utils.owner_access import is_bot_owner_id

logger = logging.getLogger("bot.dashboard.admin-only")
_INSTALLED = False

_PRIVATE_PAGE_PATHS = {"/app", "/setup-center"}
_PUBLIC_RUNTIME_RELAY_PATH = "/api/runtime/slash-heartbeat"

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
    """Construit l'entrée affichée sans dépendre d'un objet membre mis en cache."""
    icon_url = str(guild.icon.url) if getattr(guild, "icon", None) else None
    return {
        "id": str(guild.id),
        "name": guild.name,
        "icon_url": icon_url,
        "owner": guild.owner_id == user_id,
        **({k: v for k, v in (previous or {}).items() if k not in {"id", "name", "icon_url", "owner"}}),
    }


# Une permission validée peut être réutilisée pendant la même fenêtre que le contrôle live.
# Cela évite que /api/guilds/<id> réussisse puis que /sanctions, /logs, etc. échoue juste
# après à cause d'un second fetch Discord ou d'un cache membres incomplet sur l'instance HA.
ADMIN_REFRESH_TTL_SECONDS = 30.0
ADMIN_MEMBER_NEGATIVE_TTL_SECONDS = 5.0
_REFRESH_STAMP_KEY = "_admin_guilds_verified_at"
_OAUTH_GUILDS_KEY = "_oauth_admin_guilds"
_ADMIN_MEMBER_CACHE: dict[tuple[int, int], tuple[float, discord.Member | None]] = {}


def _oauth_admin_candidates(session: dict) -> list[dict]:
    """Conserve la liste OAuth d'origine séparément de la liste live vérifiée.

    ``session['guilds']`` est rafraîchie régulièrement. Sans copie immuable, un faux négatif
    temporaire supprimait définitivement le serveur de la session et les requêtes suivantes
    n'avaient plus aucun candidat à revérifier.
    """
    saved = session.get(_OAUTH_GUILDS_KEY)
    if not isinstance(saved, list):
        saved = [dict(item) for item in session.get("guilds", []) if isinstance(item, dict)]
        session[_OAUTH_GUILDS_KEY] = saved
    return [dict(item) for item in saved if isinstance(item, dict)]


async def _administrator_member_cached(guild: discord.Guild, user_id: int) -> discord.Member | None:
    """Vérifie Administrateur sans faux 404 entre deux appels du même dashboard.

    Le cache gateway est préféré. S'il ne contient pas le membre, même sur un guild marqué
    ``chunked``, on autorise UN fetch ciblé pour un serveur candidat OAuth. Un résultat
    positif est ensuite réutilisé 30 s par toutes les routes de la page. Les absences sont
    gardées seulement 5 s afin de ne pas bloquer longtemps une permission fraîchement ajoutée.
    """
    key = (int(guild.id), int(user_id))
    now_mono = time.monotonic()

    member = guild.get_member(user_id)
    if member is not None:
        result = member if member.guild_permissions.administrator else None
        ttl = ADMIN_REFRESH_TTL_SECONDS if result is not None else ADMIN_MEMBER_NEGATIVE_TTL_SECONDS
        _ADMIN_MEMBER_CACHE[key] = (now_mono + ttl, result)
        return result

    cached = _ADMIN_MEMBER_CACHE.get(key)
    if cached and cached[0] > now_mono:
        return cached[1]
    if cached:
        _ADMIN_MEMBER_CACHE.pop(key, None)

    try:
        member = await guild.fetch_member(user_id)
    except discord.NotFound:
        _ADMIN_MEMBER_CACHE[key] = (now_mono + ADMIN_MEMBER_NEGATIVE_TTL_SECONDS, None)
        return None
    except (discord.Forbidden, discord.HTTPException) as exc:
        # Ne jamais transformer une panne/rate-limit Discord en refus persistant.
        logger.warning(
            "Vérification Administrateur temporairement impossible guild=%s user=%s (%s).",
            getattr(guild, "id", "?"),
            user_id,
            type(exc).__name__,
        )
        return None

    result = member if member.guild_permissions.administrator else None
    ttl = ADMIN_REFRESH_TTL_SECONDS if result is not None else ADMIN_MEMBER_NEGATIVE_TTL_SECONDS
    _ADMIN_MEMBER_CACHE[key] = (now_mono + ttl, result)
    return result


async def _refresh_admin_guilds(request: web.Request, dashboard, session: dict) -> bool:
    """Rafraîchit uniquement les serveurs plausibles, pas tous les serveurs du bot.

    La liste OAuth d'origine indique les serveurs où le compte était Administrateur au login.
    On y ajoute seulement les serveurs où le membre est déjà présent dans le cache gateway,
    ce qui permet de détecter une permission ajoutée sans lancer de scan REST global. Chaque
    candidat installé passe ensuite par le cache de vérification ciblé ci-dessus.
    """
    bot = request.app["bot"]
    try:
        user_id = int(session["user"]["id"])
    except (KeyError, TypeError, ValueError):
        return False

    verified_at = session.get(_REFRESH_STAMP_KEY)
    if isinstance(verified_at, (int, float)) and 0 <= time.time() - float(verified_at) < ADMIN_REFRESH_TTL_SECONDS:
        return bool(session.get("guilds"))

    oauth_candidates = _oauth_admin_candidates(session)
    previous_by_id: dict[int, dict] = {}
    ordered_ids: list[int] = []
    for item in [*oauth_candidates, *list(session.get("guilds", []))]:
        try:
            guild_id = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        previous_by_id.setdefault(guild_id, item)
        if guild_id not in ordered_ids:
            ordered_ids.append(guild_id)

    # Une permission admin accordée depuis le login doit aussi pouvoir apparaître. On ne
    # sonde aucun serveur arbitraire : seuls les membres déjà présents en cache sont ajoutés.
    for guild in list(bot.guilds):
        member = guild.get_member(user_id)
        if member is not None and member.guild_permissions.administrator:
            previous_by_id.setdefault(guild.id, _installed_item(guild, user_id))
            if guild.id not in ordered_ids:
                ordered_ids.append(guild.id)

    verified: list[dict] = []
    for guild_id in ordered_ids:
        previous = previous_by_id[guild_id]
        guild = bot.get_guild(guild_id)
        if guild is None:
            # SentriX n'est pas installé sur ce serveur OAuth : on le garde pour le bouton
            # d'invitation, exactement comme le dashboard historique.
            if any(str(item.get("id")) == str(guild_id) for item in oauth_candidates):
                verified.append(previous)
            continue
        if await dashboard._administrator_member(guild, user_id) is None:
            continue
        verified.append(_installed_item(guild, user_id, previous))

    session["guilds"] = verified
    session[_REFRESH_STAMP_KEY] = time.time()
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

    # Toutes les routes canoniques (_manageable_guild, /api/guilds, sanctions, logs, etc.)
    # utilisent le même verdict pendant 30 s. On évite ainsi le cas observé où la fiche du
    # serveur charge, puis la page Modération reçoit immédiatement un deuxième faux 404.
    dashboard._administrator_member = _administrator_member_cached

    original_build_app = dashboard.build_app

    @web.middleware
    async def administrator_only(request: web.Request, handler):
        path = request.path

        # Le formulaire de recours est volontairement public : son token aléatoire est
        # l'autorisation d'accès. Le relais runtime est lui aussi public mais n'accepte
        # que de la télémétrie bornée et sans donnée utilisateur/secrète ; il doit pouvoir
        # recevoir les heartbeats des autres services Railway sans session OAuth Discord.
        public_appeal_api = path.startswith("/api/appeal/")
        public_runtime_relay = path == _PUBLIC_RUNTIME_RELAY_PATH
        if (
            path in {"/health", "/login", "/oauth/callback", "/logout", "/api/public"}
            or public_appeal_api
            or public_runtime_relay
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
    logger.info("Dashboard verrouillé : Administrateur requis, vérification ciblée et cache cohérent 30 s.")
