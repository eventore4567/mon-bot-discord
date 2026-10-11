"""Proxy HA du dashboard SentriX.

Le domaine public officiel peut pointer vers une instance HA passive. Cette instance doit
continuer a exposer son /health local, mais les pages du dashboard, OAuth et API doivent
etre servies par l'instance qui possede le lease Redis et donc l'etat Discord vivant.

Le proxy reste interne a Railway (railway.internal), conserve les cookies/redirects et
ajoute une garde anti-boucle. Aucun secret n'est expose au navigateur.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from aiohttp import ClientSession, ClientTimeout, DummyCookieJar, web
from multidict import CIMultiDict

from .http_surfaces import sign_proxy_headers

logger = logging.getLogger("bot.dashboard-ha-proxy")

_LOCAL_ONLY_PATHS = frozenset({"/health", "/ready"})
_HOP_BY_HOP = frozenset({
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
})
_PROXY_HEADER = "X-SentriX-HA-Proxy"
_SESSION_KEY = "sentrix_ha_dashboard_proxy_session"
_INSTALLED = False


def _dashboard_unavailable(request: web.Request, reason: str) -> web.Response:
    """Page de repli lisible pour les NAVIGATIONS, JSON pour les API/OAuth.

    Une indisponibilité du peer HA ne signifie pas « maintenance du bot » :
    le navigateur peut retenter sans perdre sa session ni ouvrir un faux login.
    Ne jamais recopier les détails internes de l'erreur dans le HTML.
    """
    if request.method not in {"GET", "HEAD"} or (
        not request.path.startswith(("/", "/app", "/dashboard"))
        or request.path.startswith(("/api", "/oauth", "/verify", "/health", "/ready", "/login"))
    ):
        response = web.json_response(
            {"ok": False, "error": "dashboard_temporary_unavailable", "retry_after": 5},
            status=503,
        )
    elif "text/html" not in request.headers.get("Accept", ""):
        response = web.json_response(
            {"ok": False, "error": "dashboard_temporary_unavailable", "retry_after": 5},
            status=503,
        )
    else:
        html = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#07091a"><title>SentriX · Reconnexion du dashboard</title>
<style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}
*{box-sizing:border-box}body{margin:0;min-height:100svh;display:grid;place-items:center;padding:24px;
background:radial-gradient(ellipse 70% 55% at 50% 5%,#272256 0%,transparent 67%),
radial-gradient(ellipse 60% 35% at 100% 100%,#152747 0%,transparent 75%),#07091a;color:#f5f5ff}
main{max-width:600px;width:100%;border:1px solid #36315f;border-radius:24px;padding:clamp(25px,5vw,44px);
background:linear-gradient(148deg,rgba(30,29,66,.94),rgba(12,16,40,.96));box-shadow:0 28px 90px #0006}
header{display:flex;align-items:center;gap:12px;color:#dad0ff;font-size:13px;font-weight:800;letter-spacing:.19em}
.logo{width:42px;height:42px;display:grid;place-items:center;border-radius:13px;
background:linear-gradient(145deg,#8c7af2,#5d59ce);color:white;font-size:23px;box-shadow:0 8px 24px #8c7af23a}
.status{display:inline-flex;align-items:center;gap:9px;margin-top:34px;font-weight:650;font-size:12px;color:#e5ca9b}
.status i{width:8px;height:8px;border-radius:50%;background:#e8b968;box-shadow:0 0 0 5px #e8b96820}
h1{margin:12px 0 12px;font-size:clamp(27px,5vw,40px);letter-spacing:-.045em;line-height:1.13}
p{color:#b6b7d2;font-size:15px;line-height:1.7;margin:0}
.actions{display:flex;flex-wrap:wrap;gap:12px;margin-top:30px}
button,a{display:inline-flex;justify-content:center;align-items:center;min-height:44px;border-radius:12px;
padding:12px 17px;font:700 14px inherit;cursor:pointer;text-decoration:none}
button{color:#100c30;border:0;background:#c8b9ff}button:hover{background:#ded5ff}
a{color:#e1dafa;border:1px solid #4c466f;background:#ffffff0a}a:hover{background:#ffffff13}
footer{margin-top:27px;padding-top:19px;border-top:1px solid #ffffff18;color:#9295b9;font-size:12px}
@media(prefers-reduced-motion:no-preference){main{animation:appear .35s ease-out}@keyframes appear{from{opacity:.5;transform:translateY(9px)}to{opacity:1;transform:none}}}
</style></head><body>
<main><header><span class="logo" aria-hidden="true">S</span>SENTRIX</header>
<div class="status"><i aria-hidden="true"></i>Connexion au serveur en cours</div>
<h1>Le dashboard se reconnecte.</h1>
<p>La connexion entre nos deux instances se rétablit. Les protections du bot continuent si l’instance Discord est active.
Tu peux réessayer sans perdre ta session.</p>
<div class="actions"><button type="button" onclick="location.reload()">Réessayer maintenant</button>
<a href="https://mon-bot-discord-production-8944.up.railway.app/app" rel="noopener">Accès direct de secours ↗</a></div>
<footer>SentriX · Serveur web momentanément indisponible · Actualisation possible dans quelques secondes</footer>
</main></body></html>"""
        response = web.Response(status=503, text=html, content_type="text/html", charset="utf-8")
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Retry-After"] = "5"
    return response


def _truthy_env(name: str) -> bool:
    return (os.getenv(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _peer_base_url(role: str) -> str:
    role = (role or "").strip().lower()
    if role == "primary":
        configured = (os.getenv("SENTRIX_HA_STANDBY_INTERNAL_URL", "") or "").strip().rstrip("/")
        return configured or "http://sentrix-standby.railway.internal:8080"
    if role == "standby":
        configured = (os.getenv("SENTRIX_HA_PRIMARY_INTERNAL_URL", "") or "").strip().rstrip("/")
        return configured or "http://mon-bot-discord.railway.internal:8080"
    return ""


def _runtime_state(bot: Any, coordinator: Any | None) -> tuple[bool, bool, str, str]:
    live = coordinator or getattr(bot, "_sentrix_ha_coordinator", None)
    if live is not None:
        return (
            bool(getattr(live, "enabled", False)),
            bool(getattr(live, "is_leader", False)),
            str(getattr(live, "role", "") or "").strip().lower(),
            str(getattr(live, "state", "starting") or "starting").strip().lower(),
        )

    # Petite fenetre entre le demarrage HTTP et l'attachement du coordinateur au bot.
    # On garde un fallback environnemental sans inventer un leader : si Discord est deja
    # pret, cette instance est necessairement active ; sinon elle reste consideree passive.
    enabled = _truthy_env("SENTRIX_FAILOVER_ENABLED")
    role = (os.getenv("SENTRIX_FAILOVER_ROLE", "") or "").strip().lower()
    leader = bool(getattr(bot, "is_ready", lambda: False)()) if enabled else False
    return enabled, leader, role, "leader" if leader else "starting"


def _forward_headers(request: web.Request) -> CIMultiDict[str]:
    headers: CIMultiDict[str] = CIMultiDict()
    for name, value in request.headers.items():
        lowered = name.lower()
        if lowered in _HOP_BY_HOP or lowered in {"host", "content-length", _PROXY_HEADER.lower()}:
            continue
        headers.add(name, value)

    # Le leader doit reconstruire les URLs OAuth avec le domaine public vu par l'utilisateur,
    # pas avec son hostname railway.internal.
    forwarded_host = request.headers.get("X-Forwarded-Host") or request.host
    forwarded_proto = request.headers.get("X-Forwarded-Proto") or request.scheme
    headers["X-Forwarded-Host"] = forwarded_host.split(",")[0].strip()
    headers["X-Forwarded-Proto"] = forwarded_proto.split(",")[0].strip()
    headers[_PROXY_HEADER] = "1"
    return headers


def _response_headers(upstream) -> CIMultiDict[str]:
    headers: CIMultiDict[str] = CIMultiDict()
    for raw_name, raw_value in upstream.raw_headers:
        name = raw_name.decode("latin-1")
        value = raw_value.decode("latin-1")
        lowered = name.lower()
        if lowered in _HOP_BY_HOP or lowered == "content-length":
            continue
        headers.add(name, value)
    return headers


def install(dashboard_module: Any, coordinator: Any | None = None) -> None:
    """Installe le proxy avant la construction de l'application aiohttp."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_build_app = dashboard_module.build_app

    def build_app(bot):
        app = original_build_app(bot)

        @web.middleware
        async def leader_proxy(request: web.Request, handler):
            # Les sondes Railway doivent toujours decrire CETTE instance et ne jamais etre
            # masquees par le leader distant.
            if request.path in _LOCAL_ONLY_PATHS:
                return await handler(request)

            enabled, leader, role, state = _runtime_state(bot, coordinator)
            if not enabled or leader:
                return await handler(request)

            # Une requete deja proxifiee ne doit jamais rebondir entre les deux services.
            if request.headers.get(_PROXY_HEADER) == "1":
                return _dashboard_unavailable(request, "leader_unavailable")

            peer_base = _peer_base_url(role)
            if not peer_base:
                return _dashboard_unavailable(request, "ha_peer_unknown")

            session: ClientSession = request.app[_SESSION_KEY]
            target = f"{peer_base}{request.rel_url}"
            try:
                body = await request.read()
                headers = sign_proxy_headers(request, _forward_headers(request), body)
                async with session.request(
                    request.method,
                    target,
                    headers=headers,
                    data=body if body else None,
                    allow_redirects=False,
                ) as upstream:
                    payload = await upstream.read()
                    return web.Response(
                        status=upstream.status,
                        body=payload,
                        headers=_response_headers(upstream),
                    )
            except Exception as exc:
                logger.warning(
                    "Proxy dashboard HA impossible role=%s state=%s target=%s: %s",
                    role,
                    state,
                    target,
                    exc,
                )
                return _dashboard_unavailable(request, "ha_leader_unreachable")

        # Le proxy doit passer avant les middlewares applicatifs afin qu'une instance passive
        # ne tente jamais d'evaluer ses propres donnees Discord absentes.
        app.middlewares.insert(0, leader_proxy)

        async def start_proxy_session(_app):
            _app[_SESSION_KEY] = ClientSession(
                timeout=ClientTimeout(total=20, connect=5),
                auto_decompress=False,
                cookie_jar=DummyCookieJar(),
            )

        async def stop_proxy_session(_app):
            session = _app.get(_SESSION_KEY)
            if session is not None and not session.closed:
                await session.close()

        app.on_startup.append(start_proxy_session)
        app.on_cleanup.append(stop_proxy_session)
        return app

    build_app._sentrix_ha_dashboard_proxy = True
    build_app._sentrix_original = original_build_app
    dashboard_module.build_app = build_app
    logger.info("Proxy dashboard HA leader-aware installe.")
